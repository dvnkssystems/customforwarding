# Copyright (c) 2026, DVNKS Systems and contributors
"""Sales and Purchase Invoice section headings (D10).

Sales Invoice:
- customer_section has no label, so a form that names an unlabelled section
  after its only table showed "Return Against Additional References" (a
  Table MultiSelect custom field). It is titled "Details".
- items_section ("Items") holds only Update Stock and the warehouses; the
  Items grid sits in the next, unlabelled section_break_42, which such a form
  also titled "Items". items_section becomes "Stock" and section_break_42
  carries the one "Items" heading, directly above the grid.

Purchase Invoice has the same pair: sec_warehouse is labelled "Items" but
holds Scan Barcode, Update Stock and the warehouses, while the grid sits in
the unlabelled items_section after it. sec_warehouse becomes "Stock".

Property Setters only; nothing in ERPNext is edited. Idempotent.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

LABELS = {
	"Sales Invoice": {
		"customer_section": "Details",
		"items_section": "Stock",
		"section_break_42": "Items",
	},
	"Purchase Invoice": {
		"sec_warehouse": "Stock",
	},
}


def execute():
	for doctype, labels in LABELS.items():
		meta = frappe.get_meta(doctype)
		for fieldname, label in labels.items():
			if not meta.get_field(fieldname):
				continue
			make_property_setter(
				doctype, fieldname, "label", label, "Data", for_doctype=False, validate_fields_for_doctype=False
			)
		frappe.clear_cache(doctype=doctype)
