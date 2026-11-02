# Copyright (c) 2026, DVNKS Systems and contributors
"""Invoice and customer settings from Simran's ONE Freight review (2 Nov).
They apply on every site.

- Item 3: a bill's or invoice's Cost Center (header and rows) offers only the
  branch cost centers, not the company's group "ONE FREIGHT SERVICES
  COMPANY - OFS" (is_group = 0).
- Item 7: a new customer's Billing Currency starts at the company's (SAR).
  forwarding.party_validation.default_customer_currency fills it on save as
  well.
- Item 11: tax withholding is hidden on the Sales Invoice. A forwarder's
  invoices never withhold; the bill's own was hidden by A-14.
"""

import frappe

from forwarding.patches.v1_0.a14_hide_stock_fields_on_bills import set_property
from forwarding.patches.v1_0.b1_invoice_fields import set_link_filters

LEAF_COST_CENTERS = [["Cost Center", "is_group", "=", 0]]
COST_CENTER_FIELDS = {
	"Sales Invoice": "cost_center",
	"Purchase Invoice": "cost_center",
	"Sales Invoice Item": "cost_center",
	"Purchase Invoice Item": "cost_center",
}
HIDDEN = {
	"Sales Invoice": [
		"apply_tds",
		"tax_withholding_group",
		"ignore_tax_withholding_threshold",
		"section_tax_withholding_entry",
	],
}


def execute():
	for doctype, fieldname in COST_CENTER_FIELDS.items():
		if frappe.get_meta(doctype).get_field(fieldname):
			set_link_filters(doctype, fieldname, LEAF_COST_CENTERS)

	for doctype, fields in HIDDEN.items():
		meta = frappe.get_meta(doctype)
		for fieldname in fields:
			if meta.get_field(fieldname):
				set_property(doctype, fieldname, "hidden", 1)
		frappe.clear_cache(doctype=doctype)

	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	currency = company and frappe.db.get_value("Company", company, "default_currency")
	if currency:
		set_default("Customer", "default_currency", currency)


def set_default(doctype, fieldname, value):
	# Typed Text: a Check-typed setter would read "SAR" as 0.
	frappe.db.delete("Property Setter", {"doc_type": doctype, "field_name": fieldname, "property": "default"})
	frappe.make_property_setter(
		{"doctype": doctype, "fieldname": fieldname, "property": "default", "value": value, "property_type": "Text"},
		validate_fields_for_doctype=False,
	)
	frappe.clear_cache(doctype=doctype)
