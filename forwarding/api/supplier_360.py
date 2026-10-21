# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Supplier 360: everything about one supplier in a single call.

get() reads the Supplier and the records around it -- the jobs it works on,
its Transportation and Custom Clearance services, Purchase Invoices, Payment
Entries, the documents on its services and on the Supplier itself, Contacts
and Addresses -- and folds them into KPIs, banners and lists.

How a supplier is on a job (its roles):

	Handling agent	Operations.handling_agent
	Supplier	Operations.suppliers (Operations Supplier.supplier)
	Transporter	Operations transport legs (Operations Transport Leg.transporter
			in transport_container_legs / transport_package_legs),
			Transportation.transporter, Custom Clearance.transporter_name
	Broker		Custom Clearance.broker_name

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
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import flt, get_datetime, getdate, nowdate

from forwarding import party_360, supplier_banners
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
ROLES = ("Handling agent", "Supplier", "Transporter", "Broker")

# List in the payload -> DocType a user must be able to read to see it.
GUARDED = {
	"jobs": "Operations",
	"services": "Operations",
	"invoices": "Purchase Invoice",
	"payments": "Payment Entry",
	"documents": "Operations",
	"contacts": "Contact",
	"addresses": "Address",
}

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
def get(supplier):
	frappe.has_permission("Supplier", "read", supplier, throw=True)

	payload = frappe.cache.get_value(supplier_cache_key(supplier))
	if payload is None:
		payload = build(supplier)
		frappe.cache.set_value(supplier_cache_key(supplier), payload, expires_in_sec=CACHE_SECONDS)

	return party_360.for_user(payload, "supplier", GUARDED)


# -- Building the payload -----------------------------------------------------------


def build(supplier):
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

	services = _services(supplier)
	invoices, payable = _invoices(supplier, company, currency, today)
	billed_jobs = set(payable["billed_jobs"])
	for s in services:
		s["billed"] = bool(s["operations"] and s["operations"] in billed_jobs)

	jobs, active_jobs = _jobs(supplier, services)
	documents, documents_on_file = _documents(supplier, services)
	header = _supplier_header(doc, today, contacts, addresses)

	kpis = {
		"active_jobs": active_jobs,
		"open_services": sum(
			1 for s in services if s["docstatus"] < 2 and s["status"] not in DONE_STATUSES[s["doctype"]]
		),
		"payable_outstanding": flt(payable["outstanding"], 2),
		"overdue": flt(payable["overdue"], 2),
		"unbilled_services": sum(1 for s in services if s["docstatus"] < 2 and not s["billed"]),
		"billed_this_year": flt(_billed_this_year(supplier, company, today), 2),
		"documents_on_file": documents_on_file,
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
			filters={"party_type": "Supplier", "party": supplier, "docstatus": ["<", 2]},
			fields=PAYMENT_FIELDS,
			order_by="posting_date desc, creation desc",
			limit=LIST_LIMIT,
		),
		"documents": documents,
		"contacts": contacts,
		"addresses": addresses,
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
	return roles


def _jobs(supplier, services):
	"""The job list (newest first, capped) and the count of active jobs."""
	roles = _job_roles(supplier, services)
	if not roles:
		return [], 0

	rows = frappe.get_all(
		"Operations",
		filters={"name": ["in", list(roles)]},
		fields=JOB_FIELDS,
		order_by="creation desc",
	)
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


# -- Purchase Invoices ----------------------------------------------------------------


def _invoices(supplier, company, currency, today):
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
		for r in rows[:LIST_LIMIT]
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

	Returns (rows, documents_on_file) where documents_on_file counts every
	received row and every attached file, beyond the listed rows too."""
	live = [s for s in services if s["docstatus"] < 2]
	parents = [(s["doctype"], s["name"]) for s in live]
	job_of = {(s["doctype"], s["name"]): s.get("operations") or s["name"] for s in live}
	# Two services of one job carry copies of the same job documents; count once.
	rows = party_360.merge_documents(
		party_360.document_rows(parents), lambda r: job_of.get((r["source_doctype"], r["source_name"]))
	)
	file_rows = party_360.attached_file_rows("Supplier", supplier)
	on_file = sum(r["received"] for r in rows) + len(file_rows)
	return (file_rows + rows)[:DOCUMENT_LIMIT], on_file
