# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-24): a Land job's Shipment Type is FTL or LTL.

Adds Shipment Types FTL (Full Truck Load) and LTL (Less than Truck Load) for
Land, and disables the old Land type "LAND" when no job or booking uses it.
"TRUCK", used by existing jobs, is left as it is. Running it again changes
nothing.
"""

import frappe

LAND_TYPES = ("FTL", "LTL")


def execute():
	if not frappe.db.exists("Mode Of Shipment", "Land"):
		return
	for name in LAND_TYPES:
		if not frappe.db.exists("Shipment Type", name):
			doc = frappe.get_doc(
				{
					"doctype": "Shipment Type",
					"shipment_type": name,
					"mode_of_shipment": "Land",
					"cargo_layout": "Weight Only",
				}
			)
			doc.flags.ignore_mandatory = True
			doc.insert(ignore_permissions=True)
	if frappe.db.exists("Shipment Type", "LAND"):
		used = frappe.db.exists("Operations", {"shipment_type": "LAND"}) or frappe.db.exists(
			"Container Booking Request", {"shipment_type": "LAND"}
		)
		if not used:
			frappe.db.set_value("Shipment Type", "LAND", "disabled", 1)
