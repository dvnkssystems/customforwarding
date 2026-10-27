# Copyright (c) 2026, DVNKS Systems and contributors
"""A bill with no job needs no Project (A-03).

A site Property Setter made Purchase Invoice.project mandatory, so a bill
without a job could not be saved unless some job's Project was picked by
hand. The Project now comes only from the job (forwarding.purchase_invoice
.fill_from_job); the setter is removed.
"""

import frappe


def execute():
	frappe.db.delete(
		"Property Setter",
		{"doc_type": "Purchase Invoice", "field_name": "project", "property": "reqd"},
	)
	frappe.clear_cache(doctype="Purchase Invoice")
