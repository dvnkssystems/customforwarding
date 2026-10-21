# Copyright (c) 2026, DVNKS Systems and contributors
"""Sales Invoice section headings (D10).

- customer_section has no label, so a form that names an unlabelled section
  after its only table showed "Return Against Additional References" (a
  Table MultiSelect custom field). It is titled "Details".
- items_section ("Items") holds only Update Stock and the warehouses; the
  Items grid sits in the next, unlabelled section_break_42, which such a form
  also titled "Items". items_section becomes "Stock" and section_break_42
  carries the one "Items" heading, directly above the grid.

Property Setters only; nothing in ERPNext is edited. Idempotent.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

LABELS = {
	"customer_section": "Details",
	"items_section": "Stock",
	"section_break_42": "Items",
}


def execute():
	meta = frappe.get_meta("Sales Invoice")
	for fieldname, label in LABELS.items():
		if not meta.get_field(fieldname):
			continue
		make_property_setter(
			"Sales Invoice", fieldname, "label", label, "Data", for_doctype=False, validate_fields_for_doctype=False
		)
	frappe.clear_cache(doctype="Sales Invoice")
