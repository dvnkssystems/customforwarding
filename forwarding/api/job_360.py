# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Job 360: everything about one job in a single call.

get() reads the job and every record linked to it by `operations` --
Transportation, Custom Clearance, Sales and Purchase Invoices, and the
Payment Entries that settle those Sales Invoices -- and folds them into KPIs,
banners and merged lists. Merged rows carry source_doctype / source_name so
the page can say where each one came from.

The payload is cached for 60 seconds per job under job_360:{job}; the hooks
in forwarding.job_events drop it whenever one of those records changes.
Read permission on the job is the gate. Since the cache is shared between
users, the invoice and linked-record lists are then removed for anyone
without read access to that DocType.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, date_diff, flt, get_datetime, getdate, nowdate

from forwarding import banners as job_banners
from forwarding import party_360
from forwarding.estimation import job_figures
from forwarding.forwarding.doctype.operations.operations import (
	default_cutoff_milestones,
	get_cutoff_status,
	validate_date_order,
)
from forwarding.job_events import cache_key, clear_job_cache, worklist_version
from forwarding.services import job_allowed_service_types, job_scopes, job_service_types, job_services

CACHE_SECONDS = 60
LINKED = ("Transportation", "Custom Clearance")

JOB_FIELDS = (
	"name",
	"docstatus",
	"operations_status",
	"billing_status",
	"hold_reason",
	"customer",
	"customer_name",
	"branch",
	"creation",
	"date",
	"mode_of_shipment",
	"job_type",
	"inco_terms",
	"activity_code",
	"activity_service_type",
	"scope_of_work",
	"service_list",
	"salesman",
	"awb_number",
	"house_number",
	"port_of_loading",
	"port_of_destination",
	"loading_country",
	"destination_country",
	"etd_date",
	"atd_date",
	"eta_date",
	"ata_date",
	"free_time_days",
	"free_time_expiry",
	"vessel_name",
	"voyage_number",
	"flight_number",
	"air_line",
	"shipping_line",
	"carrier",
	"handling_agent",
	"commodity",
	"packages",
	"gross_weight",
	"net_weight",
	"cbm",
	"chargable_weight",
)

ACTUAL_FIELDS = {"atd": "atd_date", "ata": "ata_date"}

# Sections of the payload, and the DocType a user must be able to read to see them.
GUARDED = {
	("invoices", "sales"): "Sales Invoice",
	("invoices", "purchase"): "Purchase Invoice",
	("invoices", "payments"): "Payment Entry",
	("linked", "transportation"): "Transportation",
	("linked", "custom_clearance"): "Custom Clearance",
}


@frappe.whitelist(methods=["GET"])
def get(job):
	frappe.has_permission("Operations", "read", job, throw=True)

	payload = frappe.cache.get_value(cache_key(job))
	if payload is None:
		payload = build(job)
		frappe.cache.set_value(cache_key(job), payload, expires_in_sec=CACHE_SECONDS)

	return _for_user(payload)


def _job_for_update(job):
	doc = frappe.get_doc("Operations", job)
	doc.check_permission("write")
	if doc.docstatus == 2:
		frappe.throw(_("Job {0} is cancelled.").format(frappe.bold(job)))
	return doc


@frappe.whitelist(methods=["POST"])
def record_delivery(job, value=None):
	"""The free-time banner's Record delivery (A-22): the job's Delivery
	Date, which ends its free-time alert. Not after today."""
	doc = _job_for_update(job)
	value = getdate(value) if value else getdate(nowdate())
	if value > getdate(nowdate()):
		frappe.throw(_("The delivery date cannot be after today."), title=_("Date in the future"))
	if doc.docstatus == 0:
		doc.delivery_date = value
		doc.save()
	else:
		doc.db_set("delivery_date", value)
		doc.add_comment("Info", _("Delivered on {0}").format(frappe.format(value, "Date")))
	clear_job_cache(job)
	return get(job)


@frappe.whitelist(methods=["POST"])
def extend_free_time(job, until):
	"""The free-time banner's Request extension (A-22): a new free-time end
	date, recorded as the Free Time (Days) that reach it from the day free time
	started, so the expiry keeps following ATA / pickup."""
	doc = _job_for_update(job)
	until = getdate(until)
	start = doc.free_time_start()
	if not start:
		frappe.throw(_("Free time has not started yet, so there is nothing to extend."), title=_("No free time"))
	days = date_diff(until, start)
	if days <= cint(doc.free_time_days):
		frappe.throw(
			_("Pick a date after the current end ({0}).").format(frappe.format(doc.free_time_expiry, "Date")),
			title=_("Not an extension"),
		)
	previous = doc.free_time_expiry
	doc.free_time_days = days
	doc.set_free_time_expiry()
	if doc.docstatus == 0:
		doc.save()
	else:
		doc.db_set({"free_time_days": days, "free_time_expiry": doc.free_time_expiry})
	doc.add_comment(
		"Info",
		_("Free time extended from {0} to {1}").format(frappe.format(previous, "Date"), frappe.format(doc.free_time_expiry, "Date")),
	)
	clear_job_cache(job)
	return get(job)


@frappe.whitelist(methods=["POST"])
def set_cutoff_done(job, row, done=1):
	"""Tick (or untick) one cut-off Done: the SI or VGM filed days before
	sailing. row is the Job Cutoff row's name. Works on a submitted job, as
	ops update cut-offs through its life."""
	doc = frappe.get_doc("Operations", job)
	doc.check_permission("write")
	if doc.docstatus == 2:
		frappe.throw(_("Job {0} is cancelled.").format(frappe.bold(job)))
	cutoff = next((r for r in doc.get("cutoffs") or [] if r.name == row), None)
	if not cutoff:
		frappe.throw(_("No such cut-off on job {0}.").format(frappe.bold(job)))
	cutoff.is_done = 1 if cint(done) else 0
	doc.set_cutoff_status()
	cutoff.db_set({"is_done": cutoff.is_done, "cutoff_status": cutoff.cutoff_status})
	clear_job_cache(job)
	return {"is_done": cutoff.is_done, "cutoff_status": cutoff.cutoff_status}


@frappe.whitelist(methods=["POST"])
def record_actual(job, field, value=None):
	"""Record (or with an empty value, clear) the job's ATD or ATA."""
	fieldname = ACTUAL_FIELDS.get(field)
	if not fieldname:
		frappe.throw(_("Field must be one of: {0}").format(", ".join(ACTUAL_FIELDS)))

	doc = frappe.get_doc("Operations", job)
	doc.check_permission("write")
	if doc.docstatus == 2:
		frappe.throw(_("Job {0} is cancelled.").format(frappe.bold(job)))

	value = getdate(value) if value else None
	today = getdate(nowdate())
	if value and value > today:
		frappe.throw(
			_("{0} cannot be after today ({1}): it records what has already happened.").format(
				field.upper(), frappe.format(today, "Date")
			),
			title=_("Date in the future"),
		)
	if doc.docstatus == 0:
		doc.set(fieldname, value)
		doc.save()
	else:
		# A submitted job cannot be saved; set the date and what follows from it.
		doc.set(fieldname, value)
		validate_date_order(doc, pairs=(("atd_date", "ata_date"),))
		doc.set_free_time_expiry()
		doc.db_set({fieldname: value, "free_time_expiry": doc.free_time_expiry})
		# ATD means every cut-off was met: tick them Done.
		doc.set_cutoff_status()
		for row in doc.get("cutoffs") or []:
			row.db_set({"is_done": row.is_done, "cutoff_status": row.cutoff_status})
		doc.add_comment(
			"Info",
			_("{0} recorded as {1}").format(
				field.upper(), frappe.format(value, "Date") if value else _("blank")
			),
		)

	clear_job_cache(job)
	return _for_user(_cached_build(job))


def _cached_build(job):
	payload = build(job)
	frappe.cache.set_value(cache_key(job), payload, expires_in_sec=CACHE_SECONDS)
	return payload


def _for_user(payload):
	"""Drop the lists the current user may not read, and the banners they
	dismissed (A-22). Works on a copy."""
	from forwarding.banner_dismissal import hide_dismissed

	payload = dict(payload)
	job_name = (payload.get("job") or {}).get("name")
	if job_name:
		payload["banners"] = hide_dismissed("Operations", job_name, payload.get("banners"))
	for (section, key), doctype in GUARDED.items():
		if not frappe.has_permission(doctype, "read"):
			payload[section] = dict(payload[section])
			payload[section][key] = []
	return payload


# -- Building the payload -------------------------------------------------------


def job_kpis(doc, documents, charges, linked, submitted_si, today, credit_notes=()):
	"""The job's KPIs, and the ctx its banner conditions and messages see.

	Shared by build() and worklist(), so a job's worklist entries are exactly
	the banners its Job 360 page shows. credit_notes (submitted returns, with
	negative totals) net billed, collected and revenue down (A-11)."""
	received = sum(1 for d in documents if d["received"])
	pending = list(dict.fromkeys(d["document"] for d in documents if not d["received"] and d["document"]))
	cost_total = sum(flt(c["cost"]) for c in charges)
	billed_si = [*submitted_si, *credit_notes]
	revenue_total = sum(flt(si.base_net_total) for si in billed_si)

	kpis = {
		"docs_received": received,
		"docs_total": len(documents),
		"pending_documents": pending,
		"linked_count": sum(len(rows) for rows in linked.values()),
		"cost_total": flt(cost_total, 2),
		"revenue_total": flt(revenue_total, 2),
		# No cost booked yet is not a 100% margin.
		"margin_pct": flt((revenue_total - cost_total) / revenue_total * 100, 2) if revenue_total and cost_total else None,
		"billed": flt(sum(flt(si.grand_total) for si in billed_si), 2),
		"collected": flt(sum(flt(si.grand_total) - flt(si.outstanding_amount) for si in billed_si), 2),
		# The estimate (R3-35): the cost sheet's Est. Cost / Est. Selling. The
		# actuals beside it are added by build().
		**_estimate(charges),
		# A cancelled job has no free time to run out (R2-10).
		"free_days_left": date_diff(doc.free_time_expiry, today)
		if doc.free_time_expiry and cint(doc.docstatus) != 2
		else None,
		# Free time set but not started yet (R3-52): "Starts on arrival" for
		# an import until its ATA, "Starts at container pickup" for an export
		# until that cut-off has a deadline. None otherwise.
		"free_time_note": _free_time_note(doc),
	}

	ctx = dict(
		kpis,
		# What the job offers work for, within its scope (M-05, M-06): a
		# service it does not hold raises no alert.
		service_types=job_service_types(doc),
		custom_clearance_count=len(linked["Custom Clearance"]),
		overdue_invoices=[
			si.name
			for si in submitted_si
			if flt(si.outstanding_amount) > 0 and si.due_date and getdate(si.due_date) < today
		],
		today=today,
	)
	return kpis, ctx


def _free_time_note(doc):
	if cint(doc.get("docstatus")) == 2 or doc.get("free_time_expiry") or cint(doc.get("free_time_days")) <= 0:
		return None
	return _("Starts at container pickup") if doc.get("job_type") == "Export" else _("Starts on arrival")


def _margin(selling, cost):
	"""Margin % of selling, or None while either side is still zero."""
	return flt((selling - cost) / selling * 100, 2) if selling and cost else None


def _estimate(charges):
	estimate_cost = sum(flt(c["cost"]) for c in charges)
	estimate_selling = sum(flt(c["rate"]) for c in charges)
	return {
		"estimate_cost": flt(estimate_cost, 2),
		"estimate_selling": flt(estimate_selling, 2),
		"estimate_margin_pct": _margin(estimate_selling, estimate_cost),
	}


def _actuals(invoices):
	"""What has really been billed and booked (R3-35): submitted Sales
	Invoices and Purchase Invoices for the job, net of VAT in the company
	currency, credit / debit notes netted off (theirs is negative)."""
	billed = sum(flt(si.base_net_total) for si in invoices["sales"] if si.docstatus == 1)
	booked = sum(flt(pi.base_net_total) for pi in invoices["purchase"] if pi.docstatus == 1)
	return {
		"actual_billed": flt(billed, 2),
		"actual_cost": flt(booked, 2),
		"actual_margin_pct": _margin(billed, booked),
	}


def build(job):
	doc = frappe.get_doc("Operations", job)
	today = getdate(nowdate())

	linked = _linked_records(job)
	children = _child_rows([(dt, r.name) for dt in LINKED for r in linked[dt]])
	invoices = _invoices(job)

	documents = _documents(doc, linked, children)
	charges = _charges(doc, linked, children)
	units = _units(doc)
	_tag_units(units, [*documents, *charges], linked, children)
	submitted_si = [si for si in invoices["sales"] if si.docstatus == 1 and not si.is_return]
	credit_notes = [si for si in invoices["sales"] if si.docstatus == 1 and si.is_return]
	kpis, ctx = job_kpis(doc, documents, charges, linked, submitted_si, today, credit_notes)
	kpis.update(_actuals(invoices))

	cutoffs = [
		{
			"milestone": row.milestone,
			"deadline": row.deadline,
			# Before R3-54; kept for older clients (latest = deadline after the patch).
			"earliest": row.earliest,
			"latest": row.latest,
			"name": row.name,
			"is_done": cint(row.get("is_done")),
			"cutoff_status": get_cutoff_status(row.deadline, done=bool(row.get("is_done") or doc.atd_date)),
		}
		for row in doc.get("cutoffs") or []
	]

	job_fields = {f: doc.get(f) for f in JOB_FIELDS}
	# Operations has no customer_name of its own.
	job_fields["customer_name"] = (
		frappe.db.get_value("Customer", doc.customer, "customer_name", cache=True) if doc.customer else None
	)
	# The Supplier that bills for the job's Shipping Line / Carrier, so their
	# names can open the supplier page (Phase 2 §4). None when not linked.
	# Every service on the job, and the service types it offers (M-05, M-06).
	job_fields["services"] = job_services(doc)
	job_fields["service_types"] = ctx["service_types"]
	# Its scopes, and the service types they allow between them (None: all).
	# Nothing outside them is offered anywhere on the job page.
	job_fields["scopes_of_work"] = job_scopes(doc)
	job_fields["allowed_service_types"] = job_allowed_service_types(doc)
	job_fields["shipping_line_supplier"] = (
		frappe.db.get_value("Shipping Line", doc.shipping_line, "supplier") if doc.get("shipping_line") else None
	)
	job_fields["carrier_supplier"] = (
		frappe.db.get_value("Carrier", doc.carrier, "supplier") if doc.get("carrier") else None
	)

	payload = {
		"job": job_fields,
		"kpis": kpis,
		"banners": job_banners.evaluate(doc, ctx),
		"linked": {
			"transportation": [_pick(r, LINKED_FIELDS["Transportation"]) for r in linked["Transportation"]],
			"custom_clearance": [
				_pick(r, LINKED_FIELDS["Custom Clearance"]) for r in linked["Custom Clearance"]
			],
		},
		"units": units,
		"documents": documents,
		"charges": charges,
		# Est. and actual income, expense, profit and variance: the job's row of
		# the Estimation vs Actual report, from the same function (M-03).
		"estimate": job_figures(doc.name),
		"milestones": [*_milestones(doc, submitted_si, today), *_unit_milestones(doc, units, today)],
		"cutoffs": cutoffs,
		"invoices": {
			"sales": [_pick(si, INVOICE_FIELDS) for si in invoices["sales"]],
			"purchase": [_pick(pi, [*INVOICE_FIELDS, *PURCHASE_FIELDS]) for pi in invoices["purchase"]],
			"payments": invoices["payments"],
		},
	}
	# Dates and decimals to plain JSON types, so the cached copy and the
	# response are the same thing.
	return json.loads(frappe.as_json(payload))


LINKED_FIELDS = {
	"Transportation": [
		"name",
		"docstatus",
		"transporter",
		"vehicle",
		"driver",
		"departure_location",
		"destination_location",
		"transport_status",
		"modified",
		"creation",
	],
	"Custom Clearance": [
		"name",
		"docstatus",
		"bayyan_number",
		"bayyan_date",
		"clearance_status",
		"clearance_date",
		"do_number",
		"do_date",
		"start_date",
		"end_date",
		"duty_amount_company",
		"duty_amount_client",
		"broker_name",
		"transporter_name",
		"modified",
		"creation",
	],
}
# Purchase Invoice rows also say who billed (the Invoices tab links the
# supplier page).
PURCHASE_FIELDS = ["supplier", "supplier_name"]
INVOICE_FIELDS = [
	"name",
	"posting_date",
	"grand_total",
	"outstanding_amount",
	"due_date",
	"status",
	"docstatus",
]


def _pick(row, fields):
	return {f: row.get(f) for f in fields}


def _linked_records(job):
	return {
		dt: frappe.get_all(
			dt,
			filters={"operations": job, "docstatus": ["<", 2]},
			fields=LINKED_FIELDS[dt],
			order_by="creation asc",
		)
		for dt in LINKED
	}


def _child_rows(parents):
	"""Document Table and Cost Table rows of the linked records, and the jobs'
	Services and Scope Of Work rows, one query per table, grouped as
	{(parenttype, parent): {"Document Table": [...], ...}}."""
	grouped = {}
	if not parents:
		return grouped
	names = list({name for _dt, name in parents})
	types = list({dt for dt, _name in parents})

	for child, fields in (
		(
			"Document Table",
			[
				"name",
				"parent",
				"parenttype",
				"document",
				"stage",
				"received",
				"date",
				"attach",
				"remark",
				"unit",
				"idx",
			],
		),
		(
			"Cost Table",
			[
				"name",
				"parent",
				"parenttype",
				"item",
				"item_name",
				"cost",
				"rate",
				"amount",
				"paid_amount",
				"received_amount",
				"ref_id",
				"ref_docname",
				"creation",
				"unit",
				"idx",
			],
		),
		# A linked record's containers: one alone tags its rows (A-23).
		("Container Details", ["name", "parent", "parenttype", "container_no", "idx"]),
		("Operations Service", ["name", "parent", "parenttype", "activity_code", "idx"]),
		("Job Scope Of Work", ["name", "parent", "parenttype", "scope_of_work", "idx"]),
	):
		table = frappe.qb.DocType(child)
		rows = (
			frappe.qb.from_(table)
			.select(*[table[f] for f in fields])
			.where(table.parent.isin(names) & table.parenttype.isin(types))
			.orderby(table.idx)
			.run(as_dict=True)
		)
		for row in rows:
			grouped.setdefault((row.parenttype, row.parent), {}).setdefault(child, []).append(row)
	return grouped


def _documents(doc, linked, children):
	def row(r, source_doctype, source_name):
		return {
			"document": r.document,
			"stage": r.stage,
			"received": 1 if cstr(r.received).strip() == "Yes" else 0,
			"date": r.date,
			"attach": r.attach,
			"document_number": r.get("remark") or None,
			"unit_ref": r.get("unit") or None,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"row_name": r.name,
		}

	rows = [row(r, "Operations", doc.name) for r in doc.get("document_table") or []]
	for dt in LINKED:
		for parent in linked[dt]:
			for r in children.get((dt, parent.name), {}).get("Document Table", []):
				rows.append(row(r, dt, parent.name))
	# The job's own rows come first, so the merged row stays on the job.
	return party_360.merge_documents(rows, lambda _r: doc.name)


def _charges(doc, linked, children):
	"""Cost rows of the job and its linked records.

	Transportation and Custom Clearance copy their cost rows onto the job
	(the copy's name is kept in the source row's ref_id). Those rows are
	counted once, from the job, so the total is not doubled -- but they name
	the record they came from as their source, not the job.
	"""

	def row(r, source_doctype, source_name):
		return {
			"item": r.item,
			"item_name": r.item_name,
			"cost": flt(r.cost),
			"rate": flt(r.rate),
			"amount": flt(r.cost),
			"paid_amount": flt(r.paid_amount),
			"received_amount": flt(r.received_amount),
			"unit_ref": r.get("unit") or None,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"row_name": r.name,
		}

	job_rows = doc.get("cost_table") or []
	on_job = {r.name: r for r in job_rows}
	origin = {}
	extra = []
	for dt in LINKED:
		for parent in linked[dt]:
			for r in children.get((dt, parent.name), {}).get("Cost Table", []):
				copy = on_job.get(r.ref_id) if r.ref_id else None
				if not copy:
					extra.append(row(r, dt, parent.name))
				elif _copied_from(copy, parent):
					origin.setdefault(copy.name, (dt, parent.name, r.name))

	rows = []
	for r in job_rows:
		if r.name in origin:
			dt, name, origin_row = origin[r.name]
			# Named after the origin record's row; the job's copy is job_row_name.
			rows.append(dict(row(r, dt, name), row_name=origin_row, job_row_name=r.name))
		else:
			rows.append(row(r, "Operations", doc.name))
	return rows + extra


def _copied_from(job_row, parent):
	"""Whether the job's cost row was made from the linked record's row, not
	the other way round (the Create menu copies the job's rows onto a new
	Transportation, and those rows point at the job's by ref_id too).

	Copies made since C7 name their record in ref_docname. Older ones do not;
	they were written while the record was being saved, so after it existed.
	"""
	if job_row.get("ref_docname"):
		return job_row.ref_docname == parent.name
	if not (job_row.get("creation") and parent.get("creation")):
		return False
	return get_datetime(job_row.creation) >= get_datetime(parent.creation)


def _invoices(job):
	si = frappe.get_all(
		"Sales Invoice",
		filters={"operations": job, "docstatus": ["<", 2]},
		fields=[*INVOICE_FIELDS, "base_net_total", "is_return"],
		order_by="posting_date asc, creation asc",
	)
	pi = frappe.get_all(
		"Purchase Invoice",
		filters={"operations": job, "docstatus": ["<", 2]},
		fields=[*INVOICE_FIELDS, *PURCHASE_FIELDS, "base_net_total", "is_return"],
		order_by="posting_date asc, creation asc",
	)

	payments = []
	if si:
		pe = frappe.qb.DocType("Payment Entry")
		ref = frappe.qb.DocType("Payment Entry Reference")
		payments = (
			frappe.qb.from_(pe)
			.join(ref)
			.on(ref.parent == pe.name)
			.select(
				pe.name,
				pe.posting_date,
				pe.paid_amount,
				pe.payment_type,
				pe.docstatus,
				ref.reference_name.as_("against_invoice"),
			)
			.where(
				(ref.reference_doctype == "Sales Invoice")
				& ref.reference_name.isin([s.name for s in si])
				& (pe.docstatus < 2)
			)
			.orderby(pe.posting_date)
			.run(as_dict=True)
		)
	return {"sales": si, "purchase": pi, "payments": payments}


def _units(doc):
	units = []
	uom = cstr(doc.get("weight_uom")) or "Kg"
	for r in doc.get("container_details") or []:
		size = f"{r.size}'" if r.size else ""
		kind = " ".join(p for p in (size, cstr(r.container_type)) if p)
		detail = " · ".join(
			p
			for p in (
				kind if r.container_no else None,
				f"Seal {r.seal_no}" if r.seal_no else None,
				f"{cint(r.packages)} pkgs" if r.packages else None,
				f"{flt(r.weight):g} {uom}" if r.weight else None,
				f"{flt(r.volume):g} m³" if r.volume else None,
			)
			if p
		)
		units.append(
			{
				"key": r.name,
				"kind": "container",
				"label": r.container_no or kind or _("Container {0}").format(r.idx),
				"detail": detail,
				# The container's own share of the job's Cargo Details.
				"cargo": {
					"packages": cint(r.packages),
					"net_weight": flt(r.net_weight),
					"gross_weight": flt(r.weight),
					"cbm": flt(r.volume),
					"weight_uom": uom,
				},
				# Nothing can be tracked or delivered without a container number.
				"attention": not cstr(r.container_no).strip(),
			}
		)

	for r in doc.get("package_details") or []:
		dims = (
			f"{cint(r.length)}×{cint(r.width)}×{cint(r.height)} cm"  # noqa: RUF001
			if (r.length and r.width and r.height)
			else None
		)
		detail = " · ".join(
			p
			for p in (
				dims,
				f"{flt(r.total_weight or r.weight):g} kg" if (r.total_weight or r.weight) else None,
				f"{flt(r.volume):g} m³" if r.volume else None,
			)
			if p
		)
		units.append(
			{
				"key": r.name,
				"kind": "package_group",
				"label": f"{flt(r.quantity):g} × {r.package_type or _('Package')}",  # noqa: RUF001
				"detail": detail,
				# Weight and dimensions are what chargeable weight is billed on.
				"attention": not (flt(r.weight) and r.length and r.width and r.height),
			}
		)
	return units


def _unit_key_by_ref(units):
	"""A unit's key by its label, upper case: a container's number, a package
	group's "2 × Pallet"."""
	return {cstr(u["label"]).strip().upper(): u["key"] for u in units if cstr(u.get("label")).strip()}


def _tag_units(units, rows, linked, children):
	"""Each document / charge row's `unit` (A-23): the container or package
	its Container / Package field names, else the one container of the
	Transportation or Custom Clearance it came from. Untagged rows are the
	whole job's and show under every unit."""
	by_ref = _unit_key_by_ref(units)
	single = {}
	for dt in LINKED:
		for parent in linked[dt]:
			numbers = {
				cstr(c.container_no).strip().upper()
				for c in children.get((dt, parent.name), {}).get("Container Details", [])
				if cstr(c.get("container_no")).strip()
			}
			if len(numbers) == 1:
				single[(dt, parent.name)] = numbers.pop()
	for r in rows:
		ref = cstr(r.pop("unit_ref", None)).strip().upper() or single.get((r.get("source_doctype"), r.get("source_name")))
		r["unit"] = by_ref.get(ref) if ref else None


def _unit_milestones(doc, units, today):
	"""Pull out, delivery and empty return per container (A-23), from the
	job's transport legs; each row belongs to its container's unit."""
	by_ref = _unit_key_by_ref(units)
	rows = []
	for leg in doc.get("transport_container_legs") or []:
		number = cstr(leg.reference_no).strip()
		key = by_ref.get(number.upper())
		if not key:
			continue
		for field, label in (("pull_out", _("Pull out")), ("trans_delivery_date", _("Delivered")), ("empty_return", _("Empty returned"))):
			value = leg.get(field)
			rows.append(
				{
					"key": f"{field}_{leg.name}",
					"label": f"{label} · {number}",
					"planned": None,
					"actual": value,
					"status": "done" if value else "upcoming",
					"source_doctype": "Operations",
					"source_name": doc.name,
					"unit": key,
				}
			)
	return rows


def _milestone_status(planned, actual, today):
	if actual:
		return "done"
	if not planned:
		return "upcoming"
	planned = getdate(planned)
	if planned < today:
		return "overdue"
	if planned == today:
		return "due"
	return "upcoming"


def _milestones(doc, submitted_si, today):
	def ms(key, label, planned=None, actual=None, status=None):
		return {
			"key": key,
			"label": label,
			"planned": planned,
			"actual": actual,
			"status": status or _milestone_status(planned, actual, today),
			"source_doctype": "Operations",
			"source_name": doc.name,
		}

	finished = cstr(doc.operations_status).lower() in job_banners.FINISHED
	# The job's own Date, as the header shows it; creation only if it has none.
	rows = [ms("created", _("Job created"), actual=getdate(doc.get("date") or doc.creation))]

	# Cut-offs are listed once, in the payload's own cutoffs table (R2-27).

	rows.append(ms("departure", _("Departure (ETD / ATD)"), planned=doc.etd_date, actual=doc.atd_date))
	rows.append(ms("arrival", _("Arrival (ETA / ATA)"), planned=doc.eta_date, actual=doc.ata_date))

	if doc.free_time_expiry and cint(doc.docstatus) != 2:
		days = date_diff(doc.free_time_expiry, today)
		status = "done" if finished else ("overdue" if days < 0 else "due" if days <= 3 else "upcoming")
		rows.append(ms("free_time", _("Free time expires"), planned=doc.free_time_expiry, status=status))
	elif _free_time_note(doc):
		rows.append(ms("free_time", _("Free time: {0}").format(_free_time_note(doc)), status="upcoming"))

	first_invoice = min((getdate(si.posting_date) for si in submitted_si), default=None)
	rows.append(
		ms(
			"billed",
			_("Invoiced"),
			actual=first_invoice,
			status="done" if first_invoice else ("due" if finished else "upcoming"),
		)
	)
	return rows


# -- Cut-off defaults -------------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def default_cutoffs(mode_of_shipment=None, destination_country=None):
	"""Milestone names an export job's cut-offs start with, for its mode:
	Sea -> every milestone except AES Deadline (included when the destination
	country is the United States); Air -> SI Deadline and Cargo Cut-off;
	anything else -> []."""
	return default_cutoff_milestones(mode_of_shipment, destination_country)


# -- Worklist -------------------------------------------------------------------

SCOPES = ("mine", "branch", "all")
# Roles that may look beyond their own jobs.
SCOPE_ROLES = {"System Manager", "Freight Admin", "Freight Manager"}
WORKLIST_LIMIT = 200
WORKLIST_PREFIX = "job_360_worklist:"
# Closed and cancelled jobs have nothing left to act on.
INACTIVE_STATUSES = ["Closed", "Cancelled"]

WORKLIST_JOB_FIELDS = [
	"name",
	"docstatus",
	"operations_status",
	"billing_status",
	"hold_reason",
	"customer",
	"branch",
	"job_type",
	"mode_of_shipment",
	"salesman",
	"owner",
	"_assign",
	"etd_date",
	"atd_date",
	"eta_date",
	"ata_date",
	"free_time_expiry",
	# What job_service_types reads, with the job's Services rows (M-05, M-06).
	"scope_of_work",
	"activity_code",
	"svc_freight_forwarding",
	"svc_customs_clearance",
	"svc_transportation",
	"svc_packing_relocation",
	"svc_trading",
	"svc_warehousing",
	"freight_forwarding",
	"custom_clearance",
	"transport",
]


@frappe.whitelist(methods=["GET"])
def worklist(scope="mine"):
	"""Jobs needing attention, one item per (job, worklist rule) that holds.

	scope: mine (jobs the user owns, sells as the salesman, or is assigned),
	branch (jobs of the user's Employee branch; every job if they have none),
	or all. Only managers may pick branch or all; anyone else gets mine.
	"""
	frappe.has_permission("Operations", "read", throw=True)

	can_change_scope = bool(SCOPE_ROLES.intersection(frappe.get_roles()))
	if scope not in SCOPES:
		frappe.throw(_("Scope must be one of: {0}").format(", ".join(SCOPES)))
	if not can_change_scope:
		scope = "mine"

	key = f"{WORKLIST_PREFIX}{worklist_version()}:{frappe.session.user}:{scope}"
	payload = frappe.cache.get_value(key)
	if payload is None:
		payload = build_worklist(frappe.session.user, scope)
		frappe.cache.set_value(key, payload, expires_in_sec=CACHE_SECONDS)
	return dict(payload, can_change_scope=can_change_scope)


def build_worklist(user, scope):
	rules = [r for r in job_banners.get_rules() if cint(r.show_on_worklist)]
	jobs = _scoped_jobs(user, scope)
	today = getdate(nowdate())

	counters = {r.rule_code: 0 for r in rules}
	items = []
	if jobs and rules:
		names = [j.name for j in jobs]
		linked = _linked_by_job(names)
		parents = [("Operations", n) for n in names] + [
			(dt, r.name) for dt in LINKED for rows in linked.values() for r in rows[dt]
		]
		children = _child_rows(parents)
		invoices = _submitted_invoices_by_job(names)
		customer_names = _customer_names({j.customer for j in jobs if j.customer})

		for job in jobs:
			own = children.get(("Operations", job.name), {})
			job.document_table = own.get("Document Table", [])
			job.cost_table = own.get("Cost Table", [])
			job.services = own.get("Operations Service", [])
			job.scopes_of_work = own.get("Job Scope Of Work", [])
			job_linked = linked.get(job.name) or {dt: [] for dt in LINKED}

			documents = _documents(job, job_linked, children)
			charges = _charges(job, job_linked, children)
			_kpis, ctx = job_kpis(job, documents, charges, job_linked, invoices.get(job.name, []), today)

			for banner in job_banners.evaluate(job, ctx, rules=rules):
				counters[banner["rule_code"]] += 1
				items.append(
					{
						"job": job.name,
						"customer": job.customer,
						"customer_name": customer_names.get(job.customer),
						"rule_code": banner["rule_code"],
						"colour": banner["colour"],
						"priority": banner["priority"],
						"message": banner["message"],
						"action": banner["action"],
						"eta_date": job.eta_date,
						"operations_status": job.operations_status,
						"branch": job.branch,
					}
				)

	# Highest priority first; within it the soonest arrival, undated last.
	items.sort(key=lambda i: (i["priority"], i["eta_date"] is None, i["eta_date"] or today, i["job"]))
	payload = {
		"scope": scope,
		"rules": [
			{
				"rule_code": r.rule_code,
				"label": r.label or r.rule_code,
				"colour": r.colour,
				"priority": cint(r.priority),
			}
			for r in rules
		],
		"counters": counters,
		"items": items[:WORKLIST_LIMIT],
	}
	return json.loads(frappe.as_json(payload))


def _scoped_jobs(user, scope):
	filters = [
		["docstatus", "<", 2],
		["operations_status", "not in", INACTIVE_STATUSES],
	]
	or_filters = None
	sales_persons = []

	if scope == "branch":
		branch = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "branch")
		if branch:
			filters.append(["branch", "=", branch])
	elif scope == "mine":
		employees = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
		if employees:
			sales_persons = frappe.get_all(
				"Sales Person", filters={"employee": ["in", employees]}, pluck="name"
			)
		or_filters = [["owner", "=", user], ["_assign", "like", f"%{user}%"]]
		if sales_persons:
			or_filters.append(["salesman", "in", sales_persons])

	jobs = frappe.get_list(
		"Operations",
		filters=filters,
		or_filters=or_filters,
		fields=WORKLIST_JOB_FIELDS,
		order_by="eta_date asc, name asc",
		limit_page_length=0,
	)
	if scope == "mine":
		# LIKE on _assign is only a pre-filter (an e-mail can contain "_").
		jobs = [
			j
			for j in jobs
			if j.owner == user or j.salesman in sales_persons or user in _assignees(j._assign)
		]
	return jobs


def _assignees(value):
	try:
		return json.loads(value) if value else []
	except ValueError:
		return []


def _linked_by_job(names):
	grouped = {}
	for dt in LINKED:
		for row in frappe.get_all(
			dt,
			filters={"operations": ["in", names], "docstatus": ["<", 2]},
			fields=["name", "operations", "creation"],
			order_by="creation asc",
		):
			grouped.setdefault(row.operations, {d: [] for d in LINKED})[dt].append(row)
	return grouped


def _submitted_invoices_by_job(names):
	grouped = {}
	for si in frappe.get_all(
		"Sales Invoice",
		filters={"operations": ["in", names], "docstatus": 1, "is_return": 0},
		fields=[
			"name",
			"operations",
			"docstatus",
			"is_return",
			"grand_total",
			"base_net_total",
			"outstanding_amount",
			"due_date",
			"posting_date",
		],
		order_by="posting_date asc, creation asc",
	):
		grouped.setdefault(si.operations, []).append(si)
	return grouped


def _customer_names(customers):
	if not customers:
		return {}
	return dict(
		frappe.get_all(
			"Customer", filters={"name": ["in", list(customers)]}, fields=["name", "customer_name"], as_list=True
		)
	)
