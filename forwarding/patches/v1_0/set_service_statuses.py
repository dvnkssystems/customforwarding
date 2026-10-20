# Copyright (c) 2026, DVNKS Systems and contributors
"""Fill the new single status fields on Custom Clearance and Transportation.

Custom Clearance used three overlapping fields (status, document_status,
shipping_status); clearance_status replaces them in the form. The old
columns are kept (hidden) and read here:

	status Manifest Submission / Arrived to Port / Submitted Declaration -> Submitted
	status Inspection stage                                              -> Under Review
	status Ready to Release                                              -> Duty Assessed
	status Fully Release                                                 -> Released
	no status, document_status Completed                                 -> Released
	no status, shipping_status mentioning "releas"                       -> Released
	anything else                                                        -> Draft

Transportation records without a transport_status become Planned.
"""

import frappe
from frappe.utils import cstr

STATUS_MAP = {
	"manifest submission": "Submitted",
	"arrived to port": "Submitted",
	"submitted declaration": "Submitted",
	"inspection stage": "Under Review",
	"ready to release": "Duty Assessed",
	"fully release": "Released",
}


def clearance_status(status, document_status, shipping_status):
	mapped = STATUS_MAP.get(cstr(status).strip().lower())
	if mapped:
		return mapped
	if cstr(document_status).strip().lower() == "completed":
		return "Released"
	if "releas" in cstr(shipping_status).lower():
		return "Released"
	return "Draft"


def execute():
	frappe.reload_doc("forwarding", "doctype", "custom_clearance")
	frappe.reload_doc("forwarding", "doctype", "transportation")

	for row in frappe.get_all(
		"Custom Clearance", fields=["name", "status", "document_status", "shipping_status"]
	):
		frappe.db.set_value(
			"Custom Clearance",
			row.name,
			"clearance_status",
			clearance_status(row.status, row.document_status, row.shipping_status),
			update_modified=False,
		)

	t = frappe.qb.DocType("Transportation")
	(
		frappe.qb.update(t)
		.set(t.transport_status, "Planned")
		.where(t.transport_status.isnull() | (t.transport_status == ""))
		.run()
	)
