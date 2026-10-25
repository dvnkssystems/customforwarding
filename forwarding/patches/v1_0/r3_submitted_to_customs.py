# Copyright (c) 2026, DVNKS Systems and contributors
"""Custom Clearance status "Submitted" becomes "Submitted to Customs" (R3-40),
so it is never mixed up with submitting the record. Transportation's
"Dispatched" becomes "In Transit" (R3-39: Planned -> In Transit -> Delivered).

Direct updates: the records are not saved, so nothing else runs.
"""

import frappe

RENAMES = (
	("Custom Clearance", "clearance_status", "Submitted", "Submitted to Customs"),
	("Transportation", "transport_status", "Dispatched", "In Transit"),
)


def execute():
	frappe.reload_doc("forwarding", "doctype", "custom_clearance")
	frappe.reload_doc("forwarding", "doctype", "transportation")
	for doctype, fieldname, old, new in RENAMES:
		table = frappe.qb.DocType(doctype)
		frappe.qb.update(table).set(table[fieldname], new).where(table[fieldname] == old).run()
