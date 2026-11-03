# Copyright (c) 2026, DVNKS Systems and contributors
"""Connections on a Customer: its Jobs, Quotations, Invoices and Payments
(ONE Freight, 3 Nov). The strip showed only ERPNext's "Party Specific Item";
ERPNext lists the rest on the desk's dashboard from Python, which the app does
not read (as A-12 found for the Sales Invoice). Custom DocType Link rows, on
every site.
"""

import frappe

PARENT = "Customer"
LINKS = [
	{"link_doctype": "Operations", "link_fieldname": "customer", "group": "Jobs"},
	{"link_doctype": "Quotation", "link_fieldname": "party_name", "group": "Quotations"},
	{"link_doctype": "Sales Invoice", "link_fieldname": "customer", "group": "Invoices"},
	{"link_doctype": "Payment Entry", "link_fieldname": "party", "group": "Payments"},
]


def execute():
	for link in LINKS:
		filters = {"parent": PARENT, "link_doctype": link["link_doctype"], "link_fieldname": link["link_fieldname"]}
		if frappe.db.exists("DocType Link", filters):
			continue
		row = frappe.get_doc(
			{"doctype": "DocType Link", "parent": PARENT, "parenttype": "DocType", "parentfield": "links", "custom": 1, **link}
		)
		row.idx = (frappe.db.count("DocType Link", {"parent": PARENT}) or 0) + 1
		row.db_insert()
	frappe.clear_cache(doctype=PARENT)
