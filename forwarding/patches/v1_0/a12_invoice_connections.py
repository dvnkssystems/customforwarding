# Copyright (c) 2026, DVNKS Systems and contributors
"""Connections on a Sales Invoice: its Job, Payments and Credit Notes (A-12).

ERPNext lists these on the desk's dashboard from Python, which the app does
not read; the app's Connections strip reads the DocType's links. These custom
DocType Link rows give it the same three (the job through the invoice's own
`operations` link, payments through their reference rows, credit notes
through `return_against`).
"""

import frappe

LINKS = [
	{"link_doctype": "Operations", "link_fieldname": "name", "group": "Job"},
	{
		"link_doctype": "Payment Entry Reference",
		"link_fieldname": "reference_name",
		"parent_doctype": "Payment Entry",
		"table_fieldname": "references",
		"is_child_table": 1,
		"group": "Payments",
	},
	{"link_doctype": "Sales Invoice", "link_fieldname": "return_against", "group": "Credit Notes"},
]


def execute():
	for link in LINKS:
		filters = {"parent": "Sales Invoice", "link_doctype": link["link_doctype"], "link_fieldname": link["link_fieldname"]}
		if frappe.db.exists("DocType Link", filters):
			continue
		row = frappe.get_doc(
			{"doctype": "DocType Link", "parent": "Sales Invoice", "parenttype": "DocType", "parentfield": "links", "custom": 1, **link}
		)
		row.idx = (frappe.db.count("DocType Link", {"parent": "Sales Invoice"}) or 0) + 1
		row.db_insert()
	frappe.clear_cache(doctype="Sales Invoice")
