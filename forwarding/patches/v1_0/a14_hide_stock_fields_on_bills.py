# Copyright (c) 2026, DVNKS Systems and contributors
"""Fields a freight forwarder's bills never use, hidden (A-14, A-18, A-20, A-34).

Charges are services (no item keeps stock), so the stock section and the
row warehouse go; the return / debit-note tick-boxes give way to Create →
Credit Note (A-11); tax withholding, shipping rules, pricing-rule overrides
and India's GST Transporter ID do not apply here.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

HIDDEN = {
	"Sales Invoice": ["is_return", "is_debit_note", "items_section", "update_stock"],
	"Sales Invoice Item": ["warehouse"],
	"Purchase Invoice": [
		"sec_warehouse",
		"update_stock",
		"update_cost",
		"is_return",
		"apply_tds",
		"shipping_rule",
		"ignore_pricing_rule",
	],
	"Purchase Invoice Item": ["warehouse"],
	"Payment Entry": ["apply_tds"],
	"Supplier": ["gst_transporter_id"],
}
# Grid columns as well as the row form.
NOT_IN_GRID = {"Sales Invoice Item": ["warehouse"], "Purchase Invoice Item": ["warehouse"]}


def set_property(doctype, fieldname, prop, value):
	existing = frappe.db.get_value(
		"Property Setter", {"doc_type": doctype, "field_name": fieldname, "property": prop}
	)
	if existing:
		frappe.db.set_value("Property Setter", existing, "value", str(value))
	else:
		make_property_setter(doctype, fieldname, prop, value, "Check", validate_fields_for_doctype=False)


def execute():
	for doctype, fields in HIDDEN.items():
		meta = frappe.get_meta(doctype)
		for fieldname in fields:
			if meta.get_field(fieldname):
				set_property(doctype, fieldname, "hidden", 1)
		for fieldname in NOT_IN_GRID.get(doctype, []):
			if meta.get_field(fieldname):
				set_property(doctype, fieldname, "in_list_view", 0)
		frappe.clear_cache(doctype=doctype)
