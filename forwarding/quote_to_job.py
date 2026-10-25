# Copyright (c) 2026, DVNKS Systems and contributors
"""Turn a Quote into a freight job.

`Quote` is what the sales side writes; `Operations` is the job the operations
side runs. Nothing joined the two: the desk had no button, and the app's
"Approve & Create Job" waited 600ms and opened an empty form, so every figure
was retyped by hand.

What the mapping can and cannot carry:

* Amounts come across as the quote line's `amount`, which is already in company
  currency. A line carries its own currency and exchange rate — a USD line of
  3,500 records an amount of 13,160 — and the job's Cost Table has no currency
  of its own, so the converted figure is the only one that means anything
  beside the other lines. Multiplying rate by units would under-bill every
  foreign line.
* A quote line names its charge Item (R3-44), which the estimate row takes
  along with Est. Selling (the line's amount) and Est. Cost (its Est. Cost
  Amount). An older line has only free text: it lands in `item_name` and the
  Item stays empty for whoever prices the job.
* Ports are free text on a quote and Links on a job, and the port master holds
  42,000 records under several naming conventions — Jeddah alone is there three
  times. A port is filled only when the text names exactly one record for the
  job's mode (see `_resolve_port`); otherwise the text lands in the Place of
  Loading / Delivery beside the Link and the Link is left for the user.
* A quote names its branch, job type and scopes of work (R3-45), which the
  job takes as they are. An older quote has none, so they are derived from
  the resolved ports: a Saudi destination makes an import, a Saudi origin an
  export; the Saudi port's city names the branch; mode and direction name the
  service ("Sea Freight Import"). Each is set only when it resolves to a real
  record, so nothing reads as chosen when it was guessed.

The job comes back unsaved, as a draft for someone to complete.
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.query_builder.functions import Lower
from frappe.utils import add_days, date_diff, flt, nowdate

# Quote spells its modes in upper case; the Mode Of Shipment master in title case.
MODES = {
	"SEA": "Sea",
	"AIR": "Air",
	"LAND": "Land",
	"OTHER": "Others",
}


@frappe.whitelist(methods=["POST"])
def duplicate_quote(source_name):
	"""Copy an expired quote into a fresh one, dated today, and return its name.

	An expired quote is not reused as is — its prices were valid for a window
	that has passed — but its lines are worth keeping. The copy runs from today
	for as many days as the original did (7 when the original had no validity),
	and notes which quote it came from. The original is left untouched.
	"""
	source = frappe.get_doc("Quote", source_name)
	source.check_permission("read")
	frappe.has_permission("Quote", "create", throw=True)

	span = 7
	if source.date and source.validity:
		span = max(date_diff(source.validity, source.date), 1)

	copy = frappe.copy_doc(source)
	# The copy is a new draft to approve again, whatever state the original is in.
	copy.docstatus = 0
	copy.amended_from = None
	copy.status = "Draft"
	copy.date = nowdate()
	copy.validity = add_days(copy.date, span)
	copy.insert()
	copy.add_comment("Info", _("Duplicated from expired quote {0}").format(source.name))
	return copy.name


@frappe.whitelist()
def make_operations_from_quote(source_name, target_doc=None):
	"""Map a Quote onto a new, unsaved Operations document.

	Only a submitted quote that has not expired makes a job (M-07, M-08)."""
	from forwarding.quote import assert_can_make_job, job_customer

	assert_can_make_job(source_name)
	# The quote's Customer bills the job; a prospect is converted first (R3-43).
	customer = job_customer(frappe.get_doc("Quote", source_name))

	def update_item(source, target, source_parent):
		"""A quote row becomes an estimate row (R3-44): its Item, Est.
		Selling = the row's Amount and Est. Cost = its Est. Cost Amount, both
		in company currency. Item Name is the Item's name; a row with no Item
		(older quotes) keeps its description there."""
		target.rate = flt(source.amount) or flt(source.rate) * flt(source.units or 1) * flt(source.get("ex_rate") or 1)
		target.cost = flt(source.get("cost_amount")) or flt(source.get("est_cost")) * flt(source.units or 1) * flt(
			source.get("ex_rate") or 1
		)
		target.item = source.get("item") or None
		item_name = frappe.db.get_value("Item", target.item, "item_name") if target.item else None
		target.item_name = item_name or (source.description or "").strip()

	def postprocess(source, target):
		target.customer = customer
		mode = MODES.get((source.mode or "").strip().upper())
		if mode and frappe.db.exists("Mode Of Shipment", mode):
			target.mode_of_shipment = mode

		shipment_type = _shipment_type(source, mode)
		if shipment_type:
			target.shipment_type = shipment_type
		if (source.get("cargo") or "").strip().lower() == "dg goods":
			target.dg_status = 1

		# Shipping Line / Airline by mode (R3-46); an older quote has free text.
		if mode == "Sea" and source.get("shipping_line"):
			target.shipping_line = source.shipping_line
			target.air_line = None
		elif mode == "Air" and source.get("air_line"):
			target.air_line = source.air_line
			target.shipping_line = None
			target.carrier = None
		else:
			_set_carrier(target, source.get("carrier"), mode)
		_set_parties(target, source)

		_set_place(target, "port_of_loading", "place_of_loading", source.pol, mode)
		_set_place(target, "port_of_destination", "place_of_delivery", source.pod, mode)
		_set_direction(target, mode)

		incoterm = (source.get("shipping_terms") or "").strip()
		if incoterm and frappe.db.exists("Inco Terms", incoterm):
			target.inco_terms = incoterm

		commodity = _commodity((source.get("cargo_details") or "").strip())
		if commodity:
			target.commodity = commodity

		# The job starts today, whatever day the quote was written.
		target.date = nowdate()
		target.posting_date = nowdate()

	return get_mapped_doc(
		"Quote",
		source_name,
		{
			"Quote": {
				"doctype": "Operations",
				"field_map": {
					"name": "from_quotation",
					"shipment_reference": "company_ref_no",
					"cargo_details": "cargo_description",
				},
			},
			"Quote Item": {
				"doctype": "Cost Table",
				"postprocess": update_item,
			},
			# Same multi-select as the job (R3-45).
			"Job Scope Of Work": {"doctype": "Job Scope Of Work"},
		},
		target_doc,
		postprocess,
	)


SAUDI_ARABIA = "Saudi Arabia"


def _match(doctype, text):
	"""The record named `text`, ignoring case and spacing ("Socks" finds
	"SOCKS", "  sunflower   oil " finds "SUNFLOWER OIL"), or None. Exact
	otherwise: no LIKE wildcards, so "SOCK_" never matches "SOCKS"."""
	text = " ".join((text or "").split())
	if not text:
		return None
	table = frappe.qb.DocType(doctype)
	rows = (
		frappe.qb.from_(table)
		.select(table.name)
		.where(Lower(table.name) == text.lower())
		.orderby(table.creation)
		.limit(1)
		.run()
	)
	return rows[0][0] if rows else None


def _set_carrier(target, text, mode):
	"""A quote's carrier is free text: the airline on an Air job, the shipping
	line on a Sea job. It is never a vessel name."""
	text = (text or "").strip()
	if not text:
		return
	if mode == "Air":
		target.air_line = text
		# An Air job shows Air Line only (R2-25): the same airline is not
		# kept in Carrier as well.
		target.carrier = None
		return
	if mode == "Sea":
		target.shipping_line = _match("Shipping Line", text)
	# Same fieldname, so the mapper copied the text as is; keep it only when it
	# names a Carrier record.
	target.carrier = _match("Carrier", text)


def _set_parties(target, source):
	"""Consignee, Shipper and Salesman (R2-24, M-04).

	The quote's Customer is the job's customer (R3-43). Its Consignee, when
	set, is a Customer record; the job's Consignee links a Consignee record,
	so it takes the one named like it, and a new one is added when the job
	is saved (parties_from_quote). Shipper and Salesman are copied when the quote has
	them; Salesman otherwise comes from the customer's Default Salesperson.
	"""
	target.consignee = _consignee_for(source.get("consignee"))

	shipper = (source.get("shipper") or "").strip()
	target.shipper = _match("Shipper", shipper) if shipper else None

	salesman = (source.get("salesman") or "").strip()
	if salesman and frappe.db.exists("Sales Person", salesman):
		target.salesman = salesman
	else:
		from forwarding.api.customer_360 import customer_default_salesperson

		target.salesman = customer_default_salesperson(target.get("customer"))


def _consignee_for(customer):
	"""The Consignee record named like the customer (its ID or its name)."""
	if not customer:
		return None
	name = frappe.db.get_value("Customer", customer, "customer_name") or customer
	return _match("Consignee", customer) or _match("Consignee", name)


def _shipment_type(source, mode):
	"""The job's Shipment Type: DG cargo first, then FCL / LCL on Sea, then the
	one type kept for the mode ("General Cargo - AIR", "LAND")."""
	if (source.get("cargo") or "").strip().lower() == "dg goods" and frappe.db.exists("Shipment Type", "DG Cargo"):
		return "DG Cargo"
	if mode == "Sea":
		sea = (source.get("sea_shipment_type") or "").strip()
		return sea if sea and frappe.db.exists("Shipment Type", sea) else None
	if not mode:
		return None
	types = frappe.get_all("Shipment Type", filters={"mode_of_shipment": mode, "disabled": 0}, pluck="name")
	if len(types) == 1:
		return types[0]
	exact = [t for t in types if t.upper() == mode.upper()]
	general = [t for t in types if t.lower().startswith("general cargo")]
	return (exact or general or [None])[0]


def _commodity(text):
	"""The Commodity the quote's cargo names, if the master has it. A new one
	is added only when the job is saved (commodity_from_quote), so picking a
	quote and walking away leaves no trace."""
	return _match("Commodity", text) if text else None


def parties_from_quote(job):
	"""On saving a new job made from a quote with no Consignee, add the
	quote's customer to the Consignee master and link it (as commodity_from_quote
	does for the cargo)."""
	if job.get("consignee") or not job.get("from_quotation") or not job.is_new():
		return
	customer = frappe.db.get_value("Quote", job.from_quotation, "consignee")
	if not customer:
		return
	found = _consignee_for(customer)
	if not found and frappe.has_permission("Consignee", "create"):
		name = frappe.db.get_value("Customer", customer, "customer_name") or customer
		found = frappe.get_doc({"doctype": "Consignee", "consignee": " ".join(name.split())}).insert().name
	job.consignee = found


def commodity_from_quote(job):
	"""On saving a job made from a quote with no commodity, link the quote's
	cargo, adding it to the Commodity master when new (its compliance flags
	start unticked, as on any new commodity)."""
	if job.get("commodity") or not job.get("from_quotation") or not job.is_new():
		return
	text = (frappe.db.get_value("Quote", job.from_quotation, "cargo_details") or "").strip()
	if not text:
		return
	found = _match("Commodity", text)
	if not found and frappe.has_permission("Commodity", "create"):
		found = frappe.get_doc({"doctype": "Commodity", "commodity": text}).insert().name
	job.commodity = found


def _set_place(target, port_field, place_field, text, mode=None):
	"""Use the port master where the text names one record, else keep the text."""
	text = (text or "").strip()
	if not text:
		return

	port = _resolve_port(text, mode)
	if port:
		target.set(port_field, port)
	else:
		target.set(place_field, text)


def _resolve_port(text, mode=None):
	"""The one Port the text names for this mode, or None when it is ambiguous.

	A record name is taken as is. Otherwise ports whose `port_name` matches the
	text (ignoring case) are narrowed by the job's mode — Hamburg is `HAM` by air
	and `DEHAM` by sea — and then by quality: a record named `<code>-<name>` with
	a real country beats a stray `port_code-…` row or one filed under "All
	Territories". Anything still tied is left for the user; a wrong port reads as
	though someone chose it.
	"""
	if frappe.db.exists("Port", text):
		return text

	candidates = frappe.get_all(
		"Port",
		filters={"port_name": text},
		fields=["name", "port_code", "port_name", "country", "mode_of_shipment"],
	)
	if mode:
		same_mode = [c for c in candidates if c.mode_of_shipment == mode]
		candidates = same_mode or [c for c in candidates if not c.mode_of_shipment]
	if len(candidates) > 1:
		well_formed = [
			c
			for c in candidates
			if c.port_code
			and c.name == f"{c.port_code}-{c.port_name}"
			and c.country not in (None, "", "All Territories")
		]
		candidates = well_formed or candidates
	return candidates[0].name if len(candidates) == 1 else None


def _set_direction(target, mode):
	"""Job type, branch and service type, from where the cargo starts and ends.

	Only what the quote left blank: a quote now names its Branch and Job Type
	(R3-45), and those are what the job takes."""
	origin = _port_country(target.get("port_of_loading"))
	destination = _port_country(target.get("port_of_destination"))
	if destination == SAUDI_ARABIA and origin != SAUDI_ARABIA:
		job_type, saudi_port = "Import", target.get("port_of_destination")
	elif origin == SAUDI_ARABIA and destination != SAUDI_ARABIA:
		job_type, saudi_port = "Export", target.get("port_of_loading")
	else:
		return

	if target.get("job_type") and target.job_type != job_type:
		# The quote says otherwise: keep its job type and leave the rest.
		return
	if not target.get("job_type") and frappe.db.exists("Job Type", job_type):
		target.job_type = job_type

	if not target.get("branch"):
		city = (frappe.db.get_value("Port", saudi_port, "port_name") or "").upper()
		branch = next((b for b in frappe.get_all("Branch", pluck="name") if b.upper() in city.split()), None)
		if branch:
			target.branch = branch

	service = f"{mode} Freight {job_type}" if mode else None
	if not target.get("activity_code") and service and frappe.db.exists("Freight Activity Code", service):
		target.activity_code = service


def _port_country(port):
	return frappe.db.get_value("Port", port, "country") if port else None
