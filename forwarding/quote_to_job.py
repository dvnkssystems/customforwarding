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
* A quote line names its charge in free text and has no Item. The Cost Table's
  `item` and `account` are both optional, so the description lands in
  `item_name` and the two links stay empty for whoever prices the job. Those
  rows carry no Item or Account until someone fills them in, so they do not
  reach the ledger on their own.
* Ports are free text on a quote and Links on a job, and none of the text in use
  matches the port master — which holds 42,000 records under three naming
  conventions. So the text lands in the Place of Loading / Delivery beside each
  Link, and the Link is left for the user to choose.

The job comes back unsaved. `Operations` requires a branch and a job type that a
quote does not record, so it opens as a draft for someone to complete rather
than being saved with values nobody chose.
"""

import frappe
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, nowdate

# Quote spells its modes in upper case; the Mode Of Shipment master in title case.
MODES = {
	"SEA": "Sea",
	"AIR": "Air",
	"LAND": "Land",
	"OTHER": "Others",
}


@frappe.whitelist()
def make_operations_from_quote(source_name, target_doc=None):
	"""Map a Quote onto a new, unsaved Operations document."""

	def update_item(source, target, source_parent):
		target.rate = flt(source.amount) or flt(source.rate) * flt(source.units or 1)
		target.item_name = (source.description or "").strip()

	def postprocess(source, target):
		mode = MODES.get((source.mode or "").strip().upper())
		if mode and frappe.db.exists("Mode Of Shipment", mode):
			target.mode_of_shipment = mode

		# Sea Shipment Type and Shipment Type spell FCL and LCL the same way.
		shipment_type = (source.get("sea_shipment_type") or "").strip()
		if shipment_type and frappe.db.exists("Shipment Type", shipment_type):
			target.shipment_type = shipment_type

		_set_place(target, "port_of_loading", "place_of_loading", source.pol)
		_set_place(target, "port_of_destination", "place_of_delivery", source.pod)

		# `date` is mandatory on a job but optional on a quote.
		if not target.get("date"):
			target.date = nowdate()

	return get_mapped_doc(
		"Quote",
		source_name,
		{
			"Quote": {
				"doctype": "Operations",
				"field_map": {
					"name": "from_quotation",
					"consignee": "customer",
					"carrier": "vessel_name",
					"shipment_reference": "company_ref_no",
					"cargo_details": "cargo_description",
				},
			},
			"Quote Item": {
				"doctype": "Cost Table",
				"postprocess": update_item,
			},
		},
		target_doc,
		postprocess,
	)


def _set_place(target, port_field, place_field, text):
	"""Use the port master where the text names a record, else keep the text.

	An exact match is the only one taken. The master carries several spellings of
	the same place — Jeddah is there as `JEDSA-JEDDAH`, `SAJED-Jeddah islamic
	port` and `JEDDAH AIRPORT` — so guessing would pick the wrong one about as
	often as the right one, and a wrong port reads as though someone chose it.
	"""
	text = (text or "").strip()
	if not text:
		return

	if frappe.db.exists("Port", text):
		target.set(port_field, text)
	else:
		target.set(place_field, text)
