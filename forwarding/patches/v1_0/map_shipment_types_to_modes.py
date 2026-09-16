# Copyright (c) 2026, DVNKS Systems and contributors
"""Tie each Shipment Type to the Mode of Shipment it belongs to.

The job form now offers only the shipment types of the chosen mode. The mapping
follows how existing jobs already use each type. DG Cargo is retired: dangerous
goods are flagged with the DG checkbox on the job instead.

Only fills a blank mode, so a mapping someone has already corrected by hand is
left alone.
"""

import frappe

MODES = {
	"FCL": "Sea",
	"LCL": "Sea",
	"General Cargo - AIR": "Air",
	"LAND": "Land",
	"TRUCK": "Land",
	"Saber Registration": "Others",
	"IECEE registration": "Others",
	"EER REGISTRATION": "Others",
	"LAB TEST": "Others",
}

RETIRED = ("DG Cargo",)


def execute():
	for shipment_type, mode in MODES.items():
		if not frappe.db.exists("Shipment Type", shipment_type):
			continue
		if not frappe.db.exists("Mode Of Shipment", mode):
			continue
		if frappe.db.get_value("Shipment Type", shipment_type, "mode_of_shipment"):
			continue
		frappe.db.set_value("Shipment Type", shipment_type, "mode_of_shipment", mode, update_modified=False)

	for shipment_type in RETIRED:
		if frappe.db.exists("Shipment Type", shipment_type):
			frappe.db.set_value("Shipment Type", shipment_type, "disabled", 1, update_modified=False)
