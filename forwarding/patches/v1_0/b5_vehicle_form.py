# Copyright (c) 2026, DVNKS Systems and contributors
"""A transporter's truck is not a company car (A-31): Odometer, Fuel Type and
Fuel UOM stop being required, and they, Last Carbon Check, Wheels and Doors
are hidden. Make and Model stay required (ERPNext's), since the fleet tab
lists them. forwarding/custom/vehicle.json carries the same property setters
for a fresh install, plus the new Vehicle Type and the Registration (Istimara)
and Inspection (Fahas) expiry dates."""

import frappe

from forwarding.patches.v1_0.a14_hide_stock_fields_on_bills import set_property

OPTIONAL = ["last_odometer", "fuel_type", "uom"]
HIDDEN = ["last_odometer", "fuel_type", "uom", "carbon_check_date", "wheels", "doors"]


def execute():
	meta = frappe.get_meta("Vehicle")
	for fieldname in OPTIONAL:
		if meta.get_field(fieldname):
			set_property("Vehicle", fieldname, "reqd", 0)
	for fieldname in HIDDEN:
		if meta.get_field(fieldname):
			set_property("Vehicle", fieldname, "hidden", 1)
	frappe.clear_cache(doctype="Vehicle")
