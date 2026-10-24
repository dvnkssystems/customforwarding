# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Supplier 360: everything about one supplier in a single call.

get() reads the Supplier and the records around it -- the jobs it works on,
its Transportation and Custom Clearance services, Purchase Invoices, Payment
Entries, the documents on its services and on the Supplier itself, Contacts
and Addresses -- and folds them into KPIs, banners and lists.

How a supplier is on a job (its roles):

	Handling agent	Operations.handling_agent
	Supplier	Operations.suppliers (Operations Supplier.supplier), a cost row
			(Cost Table.supplier) on the job or on its Transportation /
			Custom Clearance, or a submitted Purchase Invoice for the job
	Transporter	Operations transport legs (Operations Transport Leg.transporter
			in transport_container_legs / transport_package_legs),
			Transportation.transporter, Custom Clearance.transporter_name
	Broker		Custom Clearance.broker_name
	Shipping Line	Operations.shipping_line whose Shipping Line.supplier is it
	Airline		Operations.carrier whose Carrier.supplier is it

Cancelled jobs (docstatus 2, or status Cancelled) are left out of the list.

Cost variance (Phase 2 spec §6.1) compares, per job with a submitted Purchase
Invoice from the supplier, the invoiced base_net_total with the estimate: the
job's own cost rows naming the supplier (a Transportation / Custom Clearance
cost row is copied onto the job, so the job's rows hold every charge once).
Jobs with no estimate are counted apart, not as over estimate.

Operations.shipper and customer_supplier link to the Shipper DocType, not
Supplier, and are not read.

A service is billed when its job has a submitted Purchase Invoice from this
supplier (Purchase Invoice.operations = the service's job). A service with no
job is never billed.

Money is in the company currency of the site's default company, and only that
company's bills count towards payable outstanding, overdue and billed this
year.

The payload is cached for 60 seconds per supplier under supplier_360:{supplier};
the hooks in forwarding.job_events drop it whenever one of those records
changes. Read permission on the Supplier is the gate. Since the cache is
shared between users, each list is then removed for anyone without read
access to its DocType.
"""

import json

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import date_diff, flt, get_datetime, getdate, nowdate

from forwarding import party_360, party_documents, supplier_banners
from forwarding.forwarding.doctype.party_alert_settings.party_alert_settings import get_settings
from forwarding.job_events import supplier_cache_key
from forwarding.party_360 import ADDRESS_FIELDS, CONTACT_FIELDS, default_company

CACHE_SECONDS = 60
# Rows per list. The KPIs are counted over everything, not just these rows.
LIST_LIMIT = 100
DOCUMENT_LIMIT = 200

INACTIVE_JOB_STATUSES = ("Closed", "Cancelled")
# A service in one of these is finished.
DONE_STATUSES = {
	"Transportation": ("Delivered", "Container Returned"),
	"Custom Clearance": ("Released", "Rejected"),
}
# Finished and billable: S2 nudges for a supplier invoice on these.
DELIVERED_STATUSES = {
	"Transportation": ("Delivered", "Container Returned"),
	"Custom Clearance": ("Released",),
}

# Display order of a job's roles.
ROLES = ("Handling agent", "Supplier", "Transporter", "Broker", "Shipping Line", "Airline")

# The supplier's own role tick-boxes (§4) -> pill label, in display order.
SUPPLIER_ROLES = (
	("is_transporter", "Transporter"),
	("is_handling_agent", "Handling Agent"),
	("is_broker", "Broker"),
	("is_shipping_line", "Shipping Line"),
	("is_airline", "Airline"),
	("is_overseas_agent", "Overseas Agent"),
)

# Records carrying a supplier link that make it a carrier on a job.
CARRIER_LINKS = (("Shipping Line", "shipping_line", "Shipping Line"), ("Carrier", "carrier", "Airline"))

# List in the payload -> DocType a user must be able to read to see it.
GUARDED = {
	"jobs": "Operations",
	"services": "Operations",
	"invoices": "Purchase Invoice",
	"payments": "Payment Entry",
	"documents": "Operations",
	"contacts": "Contact",
	"addresses": "Address",
	"rates": "Item Price",
	"vehicles": "Vehicle",
	"drivers": "Driver",
}

# A supplier in one of these roles quotes rates (SU5): the Rates tab.
RATE_ROLES = ("is_shipping_line", "is_airline", "is_transporter", "is_overseas_agent")

JOB_FIELDS = [
	"name",
	"operations_status",
	"mode_of_shipment",
	"job_type",
	"customer",
	"port_of_loading",
	"port_of_destination",
	"eta_date",
	"date",
	"docstatus",
	"creation",
]
PAYMENT_FIELDS = [
	"name",
	"posting_date",
	"paid_amount",
	"payment_type",
	"mode_of_payment",
	"docstatus",
	"reference_no",
]


@frappe.whitelist(methods=["GET"])
def get(supplier, from_date=None, to_date=None):
	"""The page's payload. from_date / to_date (optional, M-18) narrow the
	services (and the open / unbilled counts over them), the jobs (by job
	date) and the bill and payment lists (by posting date); payables, billed
	this year and cost variance are unchanged."""
	frappe.has_permission("Supplier", "read", supplier, throw=True)

	date_range = party_360.date_range(from_date, to_date)
	key = party_360.ranged_cache_key(supplier_cache_key(supplier), date_range)
	payload = frappe.cache.get_value(key)
	if payload is None:
		payload = build(supplier, date_range)
		frappe.cache.set_value(key, payload, expires_in_sec=CACHE_SECONDS)

	return party_360.for_user(payload, "supplier", GUARDED)


# -- Building the payload -----------------------------------------------------------


def build(supplier, date_range=None):
	doc = frappe.get_doc("Supplier", supplier)
	today = getdate(nowdate())
	company = default_company()
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None

	contacts = party_360.linked_party_records(
		"Contact", "Supplier", supplier, CONTACT_FIELDS, "is_primary_contact", LIST_LIMIT
	)
	addresses = party_360.linked_party_records(
		"Address", "Supplier", supplier, ADDRESS_FIELDS, "is_primary_address", LIST_LIMIT
	)

	all_services = _services(supplier)
	invoices, payable = _invoices(supplier, company, currency, today, date_range)
	billed_jobs = set(payable["billed_jobs"])
	for s in all_services:
		s["billed"] = bool(s["operations"] and s["operations"] in billed_jobs)
	# The date filter narrows the services listed and counted; which jobs the
	# supplier works on and its documents still come from all of them.
	services = party_360.in_range(all_services, "date", date_range)

	settings = get_settings()
	jobs, active_jobs = _jobs(supplier, all_services, date_range)
	cost_variance, jobs_over = _cost_variance(supplier, settings.cost_variance_threshold)
	expiring_rates = _expiring_rates(supplier, today, settings.rate_expiry_days)
	documents, documents_on_file, documents_total = _documents(supplier, all_services)
	# The supplier's own licences, insurance, ... (SU9): about the party, so
	# never narrowed by the date range.
	own_documents = party_documents.rows(doc, today, settings.document_expiry_days)
	document_kpis, expiring_documents, expired_documents = party_documents.summary(own_documents)
	header = _supplier_header(doc, today, contacts, addresses)
	# Rates and fleet describe the supplier, so the date range never narrows them.
	show_rates = any(doc.get(field) for field in RATE_ROLES)
	show_fleet = bool(doc.get("is_transporter"))
	rates = _rates(supplier, today, settings.rate_expiry_days)
	vehicles, drivers = _fleet(supplier, today, settings.document_expiry_days)
	fleet = _fleet_alerts(vehicles, drivers) if show_fleet else {"expiring": [], "expired": []}

	kpis = {
		"active_jobs": active_jobs,
		"open_services": sum(
			1 for s in services if s["docstatus"] < 2 and s["status"] not in DONE_STATUSES[s["doctype"]]
		),
		"payable_outstanding": flt(payable["outstanding"], 2),
		"overdue": flt(payable["overdue"], 2),
		"unbilled_services": sum(1 for s in services if s["docstatus"] < 2 and not s["billed"]),
		"billed_this_year": flt(_billed_this_year(supplier, company, today), 2),
		"cost_variance": cost_variance,
		# Service documents received and files attached, plus the supplier's
		# own documents that have a file or a number.
		"documents_on_file": documents_on_file + sum(map(party_documents.on_file, own_documents)),
		# Every listed document, received or not: the tile reads "1 / 4" as on a job.
		"documents_total": documents_total + len(own_documents),
		**document_kpis,
		"rates_count": len(rates),
		"rates_expiring": sum(1 for r in rates if r["status"] == party_documents.EXPIRING),
		"rates_expired": sum(1 for r in rates if r["status"] == party_documents.EXPIRED),
		"fleet_count": len(vehicles) + len(drivers),
		"fleet_expiring": sum(1 for r in vehicles + drivers if r["expiry_status"] == party_documents.EXPIRING),
		"fleet_expired": sum(1 for r in vehicles + drivers if r["expiry_status"] == party_documents.EXPIRED),
	}

	ctx = {
		"kpis": kpis,
		"currency": currency,
		"overdue": payable["overdue_rows"],
		"unbilled_done": [
			{"doctype": s["doctype"], "name": s["name"]}
			for s in services
			if s["docstatus"] < 2 and not s["billed"] and s["status"] in DELIVERED_STATUSES[s["doctype"]]
		],
		"supplier": header,
		"hold_type": doc.get("hold_type"),
		"release_date": doc.get("release_date"),
		"expiring_rates": expiring_rates,
		"rate_expiry_days": settings.rate_expiry_days,
		"expiring_documents": expiring_documents,
		"expired_documents": expired_documents,
		"document_expiry_days": settings.document_expiry_days,
		"show_fleet": show_fleet,
		"expiring_fleet": fleet["expiring"],
		"expired_fleet": fleet["expired"],
		"cost_variance": cost_variance,
		"jobs_over": jobs_over,
		"today": today,
	}

	payload = {
		# Every money KPI and banner amount is in this, the company's currency.
		"currency": currency,
		"supplier": header,
		"kpis": kpis,
		"banners": supplier_banners.evaluate(ctx),
		"jobs": jobs,
		"services": services[:LIST_LIMIT],
		"invoices": invoices,
		"payments": frappe.get_all(
			"Payment Entry",
			filters={
				"party_type": "Supplier",
				"party": supplier,
				"docstatus": ["<", 2],
				**party_360.range_filter("posting_date", date_range),
			},
			fields=PAYMENT_FIELDS,
			order_by="posting_date desc, creation desc",
			limit=LIST_LIMIT,
		),
		"documents": documents,
		"party_documents": own_documents,
		"contacts": contacts,
		"addresses": addresses,
		"rates": rates,
		"vehicles": vehicles,
		"drivers": drivers,
		"show_rates": show_rates,
		"show_fleet": show_fleet,
	}
	# Dates and decimals to plain JSON types, so the cached copy and the
	# response are the same thing.
	return json.loads(frappe.as_json(payload))


def _status(doc, today):
	"""Disabled, then Blocked (Freight's is_blocked or ERPNext's is_frozen),
	then On Hold (ERPNext's on_hold, until its release date), else Active."""
	if doc.disabled:
		return "Disabled"
	if doc.get("is_blocked") or doc.get("is_frozen"):
		return "Blocked"
	if doc.get("on_hold") and (not doc.get("release_date") or getdate(doc.release_date) > today):
		return "On Hold"
	return "Active"


def _supplier_header(doc, today, contacts, addresses):
	return {
		"name": doc.name,
		"supplier_name": doc.supplier_name,
		"supplier_group": doc.supplier_group,
		"country": doc.country,
		# ERPNext's tax_id, else a VAT number ksa_compliance may keep.
		"tax_id": doc.tax_id or doc.get("custom_vat_registration_number") or None,
		"supplier_code": doc.get("supplier_code") or None,
		"cr_no": doc.get("cr_no") or None,
		# Role pills (§4), from the role tick-boxes.
		"roles": [label for field, label in SUPPLIER_ROLES if doc.get(field)],
		"disabled": doc.disabled,
		"status": _status(doc, today),
		"default_currency": doc.default_currency,
		# ERPNext's Payment Terms Template, else the Freight credit period.
		"payment_terms": doc.payment_terms or doc.get("credit_period") or None,
		"primary_contact": party_360.primary_contact(doc.supplier_primary_contact, contacts),
		"primary_address": party_360.primary_address(doc.supplier_primary_address, addresses),
	}


# -- Services -----------------------------------------------------------------------


def _services(supplier):
	"""Transportation and Custom Clearance records naming the supplier,
	newest first. Every one, not capped: the KPIs count them all.

	date is the clearance's start date, else the day the record was made
	(Transportation has no date of its own)."""
	rows = []
	for r in frappe.get_all(
		"Transportation",
		filters={"transporter": supplier},
		fields=["name", "operations", "transport_status", "docstatus", "creation"],
	):
		rows.append(
			{
				"doctype": "Transportation",
				"name": r.name,
				"operations": r.operations,
				"role": "Transporter",
				"status": r.transport_status,
				"date": getdate(r.creation),
				"docstatus": r.docstatus,
				"_creation": r.creation,
			}
		)

	cc = frappe.qb.DocType("Custom Clearance")
	for r in (
		frappe.qb.from_(cc)
		.select(
			cc.name,
			cc.operations,
			cc.clearance_status,
			cc.docstatus,
			cc.start_date,
			cc.creation,
			cc.broker_name,
			cc.transporter_name,
		)
		.where((cc.broker_name == supplier) | (cc.transporter_name == supplier))
		.run(as_dict=True)
	):
		roles = [
			role
			for role, field in (("Broker", "broker_name"), ("Transporter", "transporter_name"))
			if r[field] == supplier
		]
		rows.append(
			{
				"doctype": "Custom Clearance",
				"name": r.name,
				"operations": r.operations,
				"role": ", ".join(roles),
				"status": r.clearance_status,
				"date": getdate(r.start_date or r.creation),
				"docstatus": r.docstatus,
				"_creation": r.creation,
			}
		)

	rows.sort(key=lambda s: get_datetime(s["_creation"]), reverse=True)
	for s in rows:
		del s["_creation"]
		s["billed"] = False
	return rows


# -- Jobs ---------------------------------------------------------------------------


def _job_roles(supplier, services):
	"""{job: set of roles} for every job naming the supplier."""
	roles = {}

	def add(job, role):
		if job:
			roles.setdefault(job, set()).add(role)

	for job in frappe.get_all("Operations", filters={"handling_agent": supplier}, pluck="name"):
		add(job, "Handling agent")

	for doctype, field, role in (
		("Operations Supplier", "supplier", "Supplier"),
		("Operations Transport Leg", "transporter", "Transporter"),
	):
		child = frappe.qb.DocType(doctype)
		for (job,) in (
			frappe.qb.from_(child)
			.select(child.parent)
			.distinct()
			.where((child[field] == supplier) & (child.parenttype == "Operations"))
			.run()
		):
			add(job, role)

	for s in services:
		for role in s["role"].split(", "):
			add(s["operations"], role)

	# Cost rows naming the supplier, on the job or on its services.
	ct = frappe.qb.DocType("Cost Table")
	service_jobs = {}
	for parent, parenttype in (
		frappe.qb.from_(ct)
		.select(ct.parent, ct.parenttype)
		.distinct()
		.where(
			(ct.supplier == supplier)
			& ct.parenttype.isin(["Operations", "Transportation", "Custom Clearance"])
			& (ct.parentfield == "cost_table")
		)
		.run()
	):
		if parenttype == "Operations":
			add(parent, "Supplier")
		else:
			service_jobs.setdefault(parenttype, set()).add(parent)
	for doctype, names in service_jobs.items():
		for job in frappe.get_all(doctype, filters={"name": ["in", list(names)]}, pluck="operations"):
			add(job, "Supplier")

	# Submitted bills for a job.
	for job in frappe.get_all(
		"Purchase Invoice",
		filters={"supplier": supplier, "docstatus": 1, "operations": ["is", "set"]},
		pluck="operations",
		distinct=True,
	):
		add(job, "Supplier")

	# The job's Shipping Line / Carrier is linked to the supplier.
	for doctype, job_field, role in CARRIER_LINKS:
		names = frappe.get_all(doctype, filters={"supplier": supplier}, pluck="name")
		if names:
			for job in frappe.get_all("Operations", filters={job_field: ["in", names]}, pluck="name"):
				add(job, role)
	return roles


def _jobs(supplier, services, date_range=None):
	"""The job list (newest first, capped) and the count of active jobs,
	both within date_range (by job date) when one is given."""
	roles = _job_roles(supplier, services)
	if not roles:
		return [], 0

	rows = frappe.get_all(
		"Operations",
		filters={
			"name": ["in", list(roles)],
			"docstatus": ["<", 2],
			**party_360.range_filter("date", date_range),
		},
		fields=JOB_FIELDS,
		order_by="creation desc",
	)
	rows = [r for r in rows if (r.operations_status or "") != "Cancelled"]
	active = sum(
		1
		for r in rows
		if r.docstatus < 2 and (r.operations_status or "") not in INACTIVE_JOB_STATUSES
	)

	rows = rows[:LIST_LIMIT]
	customers = {r.customer for r in rows if r.customer}
	names = (
		dict(
			frappe.get_all(
				"Customer",
				filters={"name": ["in", list(customers)]},
				fields=["name", "customer_name"],
				as_list=True,
			)
		)
		if customers
		else {}
	)
	jobs = []
	for r in rows:
		jobs.append(
			{
				"name": r.name,
				"roles": [role for role in ROLES if role in roles[r.name]],
				"operations_status": r.operations_status,
				"mode_of_shipment": r.mode_of_shipment,
				"job_type": r.job_type,
				"customer": r.customer,
				"customer_name": names.get(r.customer),
				"port_of_loading": r.port_of_loading,
				"port_of_destination": r.port_of_destination,
				"eta_date": r.eta_date,
				"date": r.date,
				"docstatus": r.docstatus,
			}
		)
	return jobs, active


# -- Cost variance and rates ------------------------------------------------------------


def _cost_variance(supplier, threshold):
	"""The Cost variance tile (§6.1) and the jobs over the threshold.

	Over every job (not cancelled) with a submitted Purchase Invoice from the
	supplier: invoiced = the bills' base_net_total (debit notes net off),
	estimated = the job's cost rows naming the supplier. pct is the overall
	(invoiced - estimated) / estimated x 100 over the jobs that have an
	estimate; a job is over estimate when its own pct exceeds threshold."""
	pi = frappe.qb.DocType("Purchase Invoice")
	ops = frappe.qb.DocType("Operations")
	invoiced = dict(
		frappe.qb.from_(pi)
		.join(ops)
		.on(ops.name == pi.operations)
		.select(pi.operations, Sum(pi.base_net_total))
		.where(
			(pi.supplier == supplier)
			& (pi.docstatus == 1)
			& (ops.docstatus < 2)
			& (Coalesce(ops.operations_status, "") != "Cancelled")
		)
		.groupby(pi.operations)
		.run()
	)
	estimated = {}
	if invoiced:
		ct = frappe.qb.DocType("Cost Table")
		estimated = dict(
			frappe.qb.from_(ct)
			.select(ct.parent, Sum(ct.cost))
			.where(
				(ct.supplier == supplier)
				& (ct.parenttype == "Operations")
				& (ct.parentfield == "cost_table")
				& ct.parent.isin(list(invoiced))
			)
			.groupby(ct.parent)
			.run()
		)

	total_est = total_inv = 0.0
	over = []
	without_estimate = 0
	for job in sorted(invoiced):
		inv, est = flt(invoiced[job]), flt(estimated.get(job))
		if est <= 0:
			without_estimate += 1
			continue
		total_est += est
		total_inv += inv
		pct = (inv - est) / est * 100
		if pct > flt(threshold):
			over.append({"job": job, "estimated": flt(est, 2), "invoiced": flt(inv, 2), "variance_pct": flt(pct, 2)})

	kpi = {
		"pct": flt((total_inv - total_est) / total_est * 100, 2) if total_est else None,
		"estimated": flt(total_est, 2),
		"invoiced": flt(total_inv, 2),
		"jobs_compared": len(invoiced) - without_estimate,
		"jobs_over_estimate": len(over),
		"jobs_without_estimate": without_estimate,
		"threshold": flt(threshold),
	}
	return kpi, over


def _expiring_rates(supplier, today, days):
	"""Buying Item Prices for the supplier whose valid_upto falls between today
	and days from now (S4)."""
	from frappe.utils import add_days

	return frappe.get_all(
		"Item Price",
		filters={
			"buying": 1,
			"supplier": supplier,
			"valid_upto": ["between", [today, add_days(today, days)]],
		},
		fields=["name", "item_code", "price_list_rate", "currency", "valid_upto"],
		order_by="valid_upto asc, name asc",
	)


def _rates(supplier, today, days):
	"""Every buying Item Price of the supplier (SU5, §5.7), expired first, then
	expiring, valid and no expiry; within each, soonest valid_upto first.

	status works like a party document's expiry: Expiring is valid_upto from
	today up to Party Alert Settings' rate_expiry_days ahead (both ends
	included, as S4 counts), Expired is valid_upto before today."""
	meta = frappe.get_meta("Item Price")
	# start_location / end_location are this app's custom fields (Port links).
	lanes = [f for f in ("start_location", "end_location") if meta.has_field(f)]
	rows = frappe.get_all(
		"Item Price",
		filters={"buying": 1, "supplier": supplier},
		fields=[
			"name",
			"item_code",
			"item_name",
			"price_list",
			"price_list_rate",
			"currency",
			"valid_from",
			"valid_upto",
			*lanes,
		],
		order_by="name asc",
	)
	out = []
	for r in rows:
		upto = getdate(r.valid_upto) if r.valid_upto else None
		out.append(
			{
				"name": r.name,
				"item_code": r.item_code,
				"item_name": r.item_name,
				"price_list": r.price_list,
				"start_location": r.get("start_location") or None,
				"end_location": r.get("end_location") or None,
				"price_list_rate": flt(r.price_list_rate),
				"currency": r.currency,
				"valid_from": r.valid_from,
				"valid_upto": upto,
				"status": party_documents.expiry_status(upto, today, days),
				"days_left": date_diff(upto, today) if upto else None,
			}
		)
	return _by_expiry(out, "status", "valid_upto", today)


def _by_expiry(rows, status_field, date_field, today):
	"""Expired, Expiring, Valid, No expiry; within each, soonest date first
	(the order rows came in breaks ties)."""
	return sorted(
		rows,
		key=lambda r: (party_documents.STATUS_ORDER[r[status_field]], r[date_field] or today),
	)


def _fleet(supplier, today, days):
	"""The transporter's Vehicles (by our Vehicle.transporter; insurance ends
	on end_date) and Drivers (ERPNext's Driver.transporter; licence ends on
	expiry_date), each ordered like the rates (SU6, §5.5)."""
	vehicles = []
	if frappe.get_meta("Vehicle").has_field("transporter"):
		for r in frappe.get_all(
			"Vehicle",
			filters={"transporter": supplier},
			fields=["name", "license_plate", "make", "model", "end_date"],
			order_by="name asc",
		):
			end = getdate(r.end_date) if r.end_date else None
			vehicles.append(
				{
					"name": r.name,
					"license_plate": r.license_plate,
					"make": r.make,
					"model": r.model,
					"insurance_end_date": end,
					"expiry_status": party_documents.expiry_status(end, today, days),
					"days_left": date_diff(end, today) if end else None,
				}
			)

	drivers = []
	for r in frappe.get_all(
		"Driver",
		filters={"transporter": supplier},
		fields=["name", "full_name", "license_number", "expiry_date"],
		order_by="name asc",
	):
		expiry = getdate(r.expiry_date) if r.expiry_date else None
		drivers.append(
			{
				"name": r.name,
				"full_name": r.full_name,
				"license_number": r.license_number or None,
				"expiry_date": expiry,
				"expiry_status": party_documents.expiry_status(expiry, today, days),
				"days_left": date_diff(expiry, today) if expiry else None,
			}
		)
	return (
		_by_expiry(vehicles, "expiry_status", "insurance_end_date", today),
		_by_expiry(drivers, "expiry_status", "expiry_date", today),
	)


def _fleet_alerts(vehicles, drivers):
	"""{expiring, expired}: [{kind, label, date}] for S5 / S9, soonest first.
	A row is in one list or the other, never both."""
	out = {"expiring": [], "expired": []}
	rows = [("Vehicle", v["license_plate"] or v["name"], v["insurance_end_date"], v["expiry_status"]) for v in vehicles]
	rows += [("Driver", d["full_name"] or d["name"], d["expiry_date"], d["expiry_status"]) for d in drivers]
	for kind, label, date, status in rows:
		if status == party_documents.EXPIRING:
			out["expiring"].append({"kind": kind, "label": label, "date": date})
		elif status == party_documents.EXPIRED:
			out["expired"].append({"kind": kind, "label": label, "date": date})
	for key in out:
		out[key].sort(key=lambda r: r["date"])
	return out


# -- Purchase Invoices ----------------------------------------------------------------


def _invoices(supplier, company, currency, today, date_range=None):
	"""The bill list, the payable totals in company currency, and the jobs
	the supplier has a submitted bill for (any company: billed is about the
	work, not the books).

	Outstanding is over every submitted bill of the company (debit notes
	included, their negative outstanding nets off), not just the listed rows.
	"""
	pi = frappe.qb.DocType("Purchase Invoice")
	rows = (
		frappe.qb.from_(pi)
		.select(
			pi.name,
			pi.bill_no,
			pi.posting_date,
			pi.due_date,
			pi.grand_total,
			pi.outstanding_amount,
			pi.status,
			pi.docstatus,
			pi.operations,
			pi.company,
			pi.party_account_currency,
			pi.conversion_rate,
		)
		.where((pi.supplier == supplier) & (pi.docstatus < 2))
		.orderby(pi.posting_date, order=frappe.qb.desc)
		.orderby(pi.creation, order=frappe.qb.desc)
		.run(as_dict=True)
	)

	outstanding = overdue = 0.0
	overdue_rows = []
	billed_jobs = set()
	for r in rows:
		if r.docstatus != 1:
			continue
		if r.operations:
			billed_jobs.add(r.operations)
		if r.company != company:
			continue
		amount = party_360.base_outstanding(r, currency)
		outstanding += amount
		if party_360.is_overdue(r, today):
			overdue += amount
			overdue_rows.append({"name": r.name, "due_date": getdate(r.due_date), "outstanding": amount})

	listed = [
		{
			"name": r.name,
			"bill_no": r.bill_no,
			"posting_date": r.posting_date,
			"due_date": r.due_date,
			"grand_total": r.grand_total,
			"outstanding_amount": r.outstanding_amount,
			"status": r.status,
			"docstatus": r.docstatus,
			"operations": r.operations,
			"overdue": party_360.is_overdue(r, today),
		}
		for r in party_360.in_range(rows, "posting_date", date_range)[:LIST_LIMIT]
	]
	return listed, {
		"outstanding": outstanding,
		"overdue": overdue,
		"overdue_rows": overdue_rows,
		"billed_jobs": billed_jobs,
	}


def _fiscal_year_bounds(company, today):
	"""(start, end) of the fiscal year today falls in; the calendar year if
	the site has none set up."""
	from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

	try:
		_name, start, end = get_fiscal_year(today, company=company)[:3]
		return getdate(start), getdate(end)
	except FiscalYearError:
		return getdate(f"{today.year}-01-01"), getdate(f"{today.year}-12-31")


def _billed_this_year(supplier, company, today):
	"""Submitted bills of the company posted this fiscal year, in company
	currency (base_grand_total; debit notes net off)."""
	if not company:
		return 0
	start, end = _fiscal_year_bounds(company, today)
	pi = frappe.qb.DocType("Purchase Invoice")
	total = (
		frappe.qb.from_(pi)
		.select(Coalesce(Sum(pi.base_grand_total), 0))
		.where(
			(pi.supplier == supplier)
			& (pi.docstatus == 1)
			& (pi.company == company)
			& (pi.posting_date >= start)
			& (pi.posting_date <= end)
		)
		.run()[0][0]
	)
	return flt(total)


# -- Documents ------------------------------------------------------------------------


def _documents(supplier, services):
	"""Files attached to the Supplier, then the Document Table rows of its
	services (newest service first).

	Returns (rows, documents_on_file, documents_total) where documents_on_file
	counts every received row and every attached file, beyond the listed rows
	too, and documents_total every row and file, received or not."""
	live = [s for s in services if s["docstatus"] < 2]
	parents = [(s["doctype"], s["name"]) for s in live]
	job_of = {(s["doctype"], s["name"]): s.get("operations") or s["name"] for s in live}
	# Two services of one job carry copies of the same job documents; count once.
	rows = party_360.merge_documents(
		party_360.document_rows(parents), lambda r: job_of.get((r["source_doctype"], r["source_name"]))
	)
	file_rows = party_360.attached_file_rows("Supplier", supplier, party_documents.attached_urls("Supplier", supplier))
	on_file = sum(r["received"] for r in rows) + len(file_rows)
	total = len(rows) + len(file_rows)
	return (file_rows + rows)[:DOCUMENT_LIMIT], on_file, total


# -- Record Payment (SU7) -------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def record_payment(supplier):
	"""An unsaved Payment Entry paying the supplier's outstanding bills.

	Pay from the company's default bank (else cash) account to the supplier's
	payable account, with a reference per submitted Purchase Invoice still
	outstanding (oldest due first), each allocated in full, and paid_amount
	their total. With nothing outstanding the header comes back on its own
	(amount 0). Built the way ERPNext's get_payment_entry builds one for a
	single invoice, from its own helpers."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import (
		get_bank_cash_account,
		get_outstanding_reference_documents,
		get_party_details,
	)

	if not frappe.has_permission("Payment Entry", "create"):
		frappe.throw(_("You do not have permission to create a Payment Entry"), frappe.PermissionError)
	frappe.has_permission("Supplier", "read", supplier, throw=True)

	company = default_company()
	if not company:
		frappe.throw(_("Set a default company before recording a payment"))
	today = nowdate()

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Pay"
	pe.company = company
	pe.posting_date = today
	pe.reference_date = today
	pe.party_type = "Supplier"
	pe.party = supplier
	pe.ensure_supplier_is_not_blocked()

	party = get_party_details(company, "Supplier", supplier, today)
	pe.party_name = party["party_name"]
	pe.paid_to = party["party_account"]
	pe.paid_to_account_currency = party["party_account_currency"]

	bank = get_bank_cash_account(pe, None)
	if bank:
		pe.paid_from = bank.account
		pe.paid_from_account_currency = bank.account_currency
	pe.bank_account = party.get("bank_account") or None
	pe.party_bank_account = party.get("party_bank_account") or None

	refs = []
	if party["party_account"]:
		refs = get_outstanding_reference_documents(
			{
				"posting_date": today,
				"company": company,
				"party_type": "Supplier",
				"party": supplier,
				"party_account": party["party_account"],
				"get_outstanding_invoices": True,
			},
			validate=True,
		) or []
	refs = sorted(
		(r for r in refs if r.voucher_type == "Purchase Invoice" and flt(r.outstanding_amount) > 0),
		key=lambda r: (getdate(r.due_date or r.posting_date), getdate(r.posting_date), r.voucher_no),
	)
	total = 0.0
	for r in refs:
		pe.append(
			"references",
			{
				"reference_doctype": "Purchase Invoice",
				"reference_name": r.voucher_no,
				"bill_no": r.get("bill_no"),
				"due_date": r.due_date,
				"payment_term": r.get("payment_term"),
				"total_amount": r.invoice_amount,
				"outstanding_amount": r.outstanding_amount,
				"allocated_amount": r.outstanding_amount,
				"exchange_rate": r.get("exchange_rate") or 1,
			},
		)
		total += flt(r.outstanding_amount)

	pe.setup_party_account_field()
	pe.set_missing_values()
	pe.set_missing_ref_details()
	if pe.paid_from and pe.paid_to:
		pe.set_exchange_rate()
		# The bills are owed in the party account's currency (received_amount);
		# paid_amount is what leaves the bank, in its currency.
		pe.received_amount = flt(total, pe.precision("received_amount"))
		if pe.paid_from_account_currency == pe.paid_to_account_currency:
			pe.paid_amount = pe.received_amount
		else:
			pe.paid_amount = flt(
				total * flt(pe.target_exchange_rate) / (flt(pe.source_exchange_rate) or 1),
				pe.precision("paid_amount"),
			)
		pe.set_amounts()
	return pe.as_dict()
