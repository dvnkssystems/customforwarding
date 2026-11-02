# Copyright (c) 2026, DVNKS Systems and contributors
"""A driver is a person on a transporter's books, not an HR or login record:
hide Driver's Employee and User fields (A-32). forwarding/custom/driver.json
carries the same property setters for a fresh install."""

import frappe

from forwarding.patches.v1_0.a14_hide_stock_fields_on_bills import set_property

HIDDEN = ["employee", "user"]


def execute():
	meta = frappe.get_meta("Driver")
	for fieldname in HIDDEN:
		if meta.get_field(fieldname):
			set_property("Driver", fieldname, "hidden", 1)
	frappe.clear_cache(doctype="Driver")
