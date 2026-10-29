# Copyright (c) 2026, DVNKS Systems and contributors
"""Each job field narrows the next (R3-24).

	Job Type LAND TRANSPORT		Mode is Land
	Mode				Shipment Type (Shipment Type.mode_of_shipment,
					the field's own link filter: Sea FCL / LCL,
					Land FTL / LTL, Air general cargo, no FCL)
	Mode				Scope of Work (Land: no Port to Port)
	Job Type + Mode + Scope		Services (forwarding.services)
	Mode				Ports: seaports for Sea, airports for Air
	Mode				Shipping Line for Sea, Airline for Air, never both
	Job Type + Mode			Estimate items (no Import VAT on an export,
					no Demurrage / Detention on an air job)

operations.js applies the same lists as set_query / set_value on the form,
which the Vue app runs through its form shim; Operations.validate calls
validate() here so a save from anywhere follows them. Checks that would
refuse an older job (ports, estimate rows) only look at what this save
changed.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr

from forwarding.services import code_mode, job_scopes

# A job type that fixes the mode.
MODE_FOR_JOB_TYPE = {"LAND TRANSPORT": "Land"}

# Scopes that do not apply to a mode.
SCOPES_NOT_FOR_MODE = {"Land": ("Port to Port",)}

# Estimate items a job may not carry, by what the item is called:
# (job_type or None, mode or None, words in the item name).
ESTIMATE_ITEM_RULES = (
	("Export", None, ("Import VAT",)),
	(None, "Air", ("Demurrage", "Detention")),
)


def mode_of(job_or_mode):
	value = job_or_mode if isinstance(job_or_mode, str) or job_or_mode is None else job_or_mode.get("mode_of_shipment")
	return code_mode(value)


def excluded_scopes(mode_of_shipment):
	return list(SCOPES_NOT_FOR_MODE.get(code_mode(mode_of_shipment), ()))


def excluded_item_words(job_type, mode_of_shipment):
	mode = code_mode(mode_of_shipment)
	words = []
	for rule_type, rule_mode, rule_words in ESTIMATE_ITEM_RULES:
		if (rule_type and rule_type != job_type) or (rule_mode and rule_mode != mode):
			continue
		words.extend(rule_words)
	return words


def item_excluded(item_name, words):
	name = cstr(item_name).lower()
	return any(w.lower() in name for w in words)


@frappe.whitelist()
def field_rules(job_type=None, mode_of_shipment=None):
	"""What the form should offer for this job type and mode:
	{mode (forced by the job type, or None), port_mode, excluded_scopes,
	excluded_item_words}. For the job form and the New Job wizard."""
	frappe.has_permission("Operations", "read", throw=True)
	forced = MODE_FOR_JOB_TYPE.get(job_type)
	mode = forced or mode_of_shipment
	return {
		"mode": forced,
		"port_mode": code_mode(mode) if code_mode(mode) in ("Sea", "Air", "Land") else None,
		"excluded_scopes": excluded_scopes(mode),
		"excluded_item_words": excluded_item_words(job_type, mode),
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def estimate_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Items for a job's Estimate rows: enabled sales items, less those
	ESTIMATE_ITEM_RULES leave out for the job type and mode
	(filters: {job_type, mode_of_shipment})."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}
	words = excluded_item_words(filters.get("job_type"), filters.get("mode_of_shipment"))
	item = frappe.qb.DocType("Item")
	query = (
		frappe.qb.from_(item)
		.select(item.name, item.item_name)
		.where(item.disabled == 0)
		.where(item.has_variants == 0)
		.where(item.name.like(f"%{txt}%") | item.item_name.like(f"%{txt}%"))
		.orderby(item.name)
		.limit(cint(page_len) or 20)
		.offset(cint(start))
	)
	for word in words:
		query = query.where(item.name.not_like(f"%{word}%")).where(item.item_name.not_like(f"%{word}%"))
	return query.run()


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""A job's Customer picker: each enabled customer with its city, not
	Customer's search fields (group, territory, mobile and the whole address,
	retest #10). The city is the primary address's, else that of the first
	linked address that has one (most customers have no primary address)."""
	customer = frappe.qb.DocType("Customer")
	rows = (
		frappe.qb.from_(customer)
		.select(customer.name, customer.customer_primary_address)
		.where(customer.disabled == 0)
		.where(customer.name.like(f"%{txt}%") | customer.customer_name.like(f"%{txt}%"))
		.orderby(customer.name)
		.limit(cint(page_len) or 20)
		.offset(cint(start))
		.run()
	)
	if not rows:
		return []

	address = frappe.qb.DocType("Address")
	link = frappe.qb.DocType("Dynamic Link")
	primary = {
		name: city
		for name, city in frappe.qb.from_(address)
		.select(address.name, address.city)
		.where(address.name.isin([r[1] for r in rows if r[1]] or [""]))
		.run()
	}
	linked = {}
	for customer_name, city in (
		frappe.qb.from_(link)
		.join(address)
		.on(address.name == link.parent)
		.select(link.link_name, address.city)
		.where(link.parenttype == "Address")
		.where(link.link_doctype == "Customer")
		.where(link.link_name.isin([r[0] for r in rows]))
		.where(address.city.isnotnull() & (address.city != ""))
		.orderby(address.is_primary_address, order=frappe.qb.desc)
		.orderby(address.creation)
		.run()
	):
		linked.setdefault(customer_name, city)
	return [(name, primary.get(primary_address) or linked.get(name) or "") for name, primary_address in rows]


def _changed(job, fieldname):
	return job.is_new() or job.has_value_changed(fieldname)


def validate(job):
	"""Operations.validate (draft saves)."""
	forced = MODE_FOR_JOB_TYPE.get(job.job_type)
	if forced and job.mode_of_shipment != forced and frappe.db.exists("Mode Of Shipment", forced):
		job.mode_of_shipment = forced
	mode = code_mode(job.mode_of_shipment)

	not_for_mode = set(excluded_scopes(job.mode_of_shipment))
	bad_scopes = [s for s in job_scopes(job) if s in not_for_mode]
	if bad_scopes:
		frappe.throw(
			_("Scope of Work {0} does not apply to a {1} job.").format(
				", ".join(frappe.bold(s) for s in bad_scopes), frappe.bold(job.mode_of_shipment)
			),
			title=_("Scope of Work"),
		)

	if mode in ("Sea", "Air", "Land"):
		for fieldname in ("port_of_loading", "port_of_destination"):
			port = job.get(fieldname)
			if not port or not _changed(job, fieldname):
				continue
			port_mode = code_mode(frappe.db.get_value("Port", port, "mode_of_shipment"))
			if port_mode and port_mode in ("Sea", "Air", "Land") and port_mode != mode:
				frappe.throw(
					_("{0} {1} is a {2} port; this is a {3} job.").format(
						_(job.meta.get_label(fieldname)).strip(), frappe.bold(port), port_mode, frappe.bold(mode)
					),
					title=_("Port"),
				)

	# Shipping Line for Sea, Airline for Air, never both: the one the mode
	# hides is cleared, so a job that changed mode does not carry both.
	if mode == "Air":
		job.shipping_line = None
	elif mode == "Sea":
		job.air_line = None
	elif job.get("shipping_line") and job.get("air_line"):
		frappe.throw(_("Choose a Shipping Line or an Airline, not both."), title=_("Carrier"))

	words = excluded_item_words(job.job_type, job.mode_of_shipment)
	if words:
		before = job.get_doc_before_save()
		old = {(r.name, r.item) for r in (before.get("cost_table") or [])} if before else set()
		bad = [
			r
			for r in job.get("cost_table") or []
			if r.item and (r.name, r.item) not in old and item_excluded(r.item_name or r.item, words)
		]
		if bad:
			frappe.throw(
				_("Estimate row {0}: {1} does not apply to this job ({2}, {3}).").format(
					bad[0].idx, frappe.bold(bad[0].item), _(job.job_type or ""), _(job.mode_of_shipment or "")
				),
				title=_("Estimate"),
			)
