# Copyright (c) 2026, DVNKS Systems and contributors
"""Make "Freight Tax Invoice" the default Sales Invoice print format (R2-06).

Sets the Property Setter `default_print_format` on Sales Invoice, which the
print view, PDF download, email attachments and the public invoice page all
fall back to when no format is named. Other formats are left as they are
(the old "With Letterhead" ones carry another company's bank details, so
they stop being the default but are not edited or deleted). Idempotent.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

PRINT_FORMAT = "Freight Tax Invoice"


def execute():
	if not frappe.db.exists("Print Format", PRINT_FORMAT):
		frappe.reload_doc("forwarding", "print_format", "freight_tax_invoice")
	if frappe.get_meta("Sales Invoice").default_print_format == PRINT_FORMAT:
		return
	make_property_setter(
		"Sales Invoice",
		None,
		"default_print_format",
		PRINT_FORMAT,
		"Data",
		for_doctype=True,
		validate_fields_for_doctype=False,
	)
	frappe.clear_cache(doctype="Sales Invoice")
