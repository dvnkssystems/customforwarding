# Copyright (c) 2026, DVNKS Systems and contributors
"""The Sales Invoice list shows Customer, Job, Status, Due Date and
Outstanding (A-13), not Title (always empty here) and Company.

The app's list takes the first five "In List View" fields, as the desk does.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

DOCTYPE = "Sales Invoice"
SHOWN = ["customer", "operations", "status", "due_date", "outstanding_amount"]


def execute():
	meta = frappe.get_meta(DOCTYPE)
	for df in meta.fields:
		if not df.fieldname:
			continue
		want = 1 if df.fieldname in SHOWN else 0
		if int(df.in_list_view or 0) == want:
			continue
		existing = frappe.db.get_value(
			"Property Setter", {"doc_type": DOCTYPE, "field_name": df.fieldname, "property": "in_list_view"}
		)
		if existing:
			frappe.db.set_value("Property Setter", existing, "value", str(want))
		else:
			make_property_setter(DOCTYPE, df.fieldname, "in_list_view", want, "Check", validate_fields_for_doctype=False)
	frappe.clear_cache(doctype=DOCTYPE)
