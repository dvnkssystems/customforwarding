# Copyright (c) 2026, DVNKS Systems and contributors
"""Retire the SEA-FCL and SEA-LCL modes of shipment.

Sea is one mode. Whether a shipment fills a container is a Shipment Type, and
the job form already offers exactly the types of the chosen mode — FCL and LCL
both sit under Sea (see map_shipment_types_to_modes). Keeping the distinction in
the mode as well gave the same fact two places to disagree.

The variants are disabled rather than deleted, so anything that still names one
keeps reading, and the records that used one are moved across first:

* Jobs on a variant take Sea, and the matching shipment type where they had
  none. A shipment type already chosen is left alone — it was chosen by hand.
* Quotations kept a vocabulary of their own — a Select of SEA-LCL / SEA-FCL /
  AIR / LAND / OTHER, with no shipment type at all. That Select loses its two
  variants and gains a Sea Shipment Type beside it, shown once the mode is SEA,
  so a quotation says what a job says.

The Quote schema half runs here rather than only in the fixture because the rows
cannot move before the column exists, and a patch that found no column would be
recorded as done and never run again.
"""

import frappe

RETIRED_MODES = ("SEA-FCL", "SEA-LCL")

# Both vocabularies spell the same split differently; each maps to a Shipment Type.
SEA_TYPES = {"SEA-FCL": "FCL", "SEA-LCL": "LCL"}

MODE_OPTIONS = "SEA\nAIR\nLAND\nOTHER"

SEA_SHIPMENT_TYPE = {
	"fieldname": "sea_shipment_type",
	"fieldtype": "Select",
	"label": "Sea Shipment Type",
	"options": "\nLCL\nFCL",
	"depends_on": 'eval:doc.mode=="SEA"',
}


def execute():
	_move_jobs()
	_retire_modes()
	if _reshape_quote():
		_move_quotes()


def _move_jobs():
	"""Jobs on a variant take Sea, keeping a shipment type someone chose by hand."""
	if not frappe.db.exists("Mode Of Shipment", "Sea"):
		return

	for old_mode, shipment_type in SEA_TYPES.items():
		for name in frappe.get_all("Operations", filters={"mode_of_shipment": old_mode}, pluck="name"):
			values = {"mode_of_shipment": "Sea"}
			if not frappe.db.get_value("Operations", name, "shipment_type"):
				if frappe.db.exists("Shipment Type", shipment_type):
					values["shipment_type"] = shipment_type
			frappe.db.set_value("Operations", name, values, update_modified=False)


def _retire_modes():
	for mode in RETIRED_MODES:
		if frappe.db.exists("Mode Of Shipment", mode):
			frappe.db.set_value("Mode Of Shipment", mode, "disabled", 1, update_modified=False)


def _reshape_quote():
	"""Narrow Quote's mode Select and add the sea shipment type beside it."""
	if not frappe.db.exists("DocType", "Quote"):
		return False

	doc = frappe.get_doc("DocType", "Quote")
	mode = next((f for f in doc.fields if f.fieldname == "mode"), None)
	if not mode:
		return False

	changed = False

	if mode.options != MODE_OPTIONS:
		mode.options = MODE_OPTIONS
		changed = True

	if not any(f.fieldname == "sea_shipment_type" for f in doc.fields):
		row = doc.append("fields", dict(SEA_SHIPMENT_TYPE))
		# append() puts it last; the field belongs next to the mode it qualifies.
		ordered = [f for f in doc.fields if f is not row]
		ordered.insert(ordered.index(mode) + 1, row)
		for position, field in enumerate(ordered, start=1):
			field.idx = position
		doc.fields = ordered
		changed = True

	if changed:
		doc.save(ignore_permissions=True)

	return True


def _move_quotes():
	for old_mode, shipment_type in SEA_TYPES.items():
		for name in frappe.get_all("Quote", filters={"mode": old_mode}, pluck="name"):
			frappe.db.set_value(
				"Quote",
				name,
				{"mode": "SEA", "sea_shipment_type": shipment_type},
				update_modified=False,
			)
