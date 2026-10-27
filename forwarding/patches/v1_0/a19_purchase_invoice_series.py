# Copyright (c) 2026, DVNKS Systems and contributors
"""Purchase Invoices are named by branch and year, PI-J-26-00001 (A-19).

The site's series PI-.{b_abb}.-.##### had no year, and b_abb was empty when
the name was made (forwarding.purchase_invoice.branch_for_naming fills it).
The new series becomes the default; the old ones stay selectable.
"""

import frappe

DOCTYPE = "Purchase Invoice"
SERIES = "PI-.{b_abb}.-.YY.-.#####"


def execute():
	options = frappe.db.get_value(
		"Property Setter", {"doc_type": DOCTYPE, "field_name": "naming_series", "property": "options"}, ["name", "value"]
	)
	if options:
		name, value = options
		rest = [s for s in (value or "").split("\n") if s and s != SERIES]
		frappe.db.set_value("Property Setter", name, "value", "\n".join([SERIES, *rest]))
	default = frappe.db.get_value(
		"Property Setter", {"doc_type": DOCTYPE, "field_name": "naming_series", "property": "default"}
	)
	if default:
		frappe.db.set_value("Property Setter", default, "value", SERIES)
	frappe.clear_cache(doctype=DOCTYPE)
