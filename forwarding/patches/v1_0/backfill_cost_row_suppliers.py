# Copyright (c) 2026, DVNKS Systems and contributors
"""Back-fill Cost Table.supplier (Phase 2 spec §5.2).

1. A Transportation's cost rows take its transporter; a Custom Clearance's
   take its transporter, else its broker.
2. A job's cost row that stands for one of those rows (the origin row's
   ref_id names it, see child_tables.sync_costs_to_job) takes the origin's
   supplier.

Rows that already name a supplier are left alone, and job rows with no
origin stay blank (a job's own rows have no default). Direct updates only:
no job or service is saved.
"""

import frappe
from frappe.query_builder.functions import Coalesce


def execute():
	frappe.reload_doc("forwarding", "doctype", "cost_table")
	ct = frappe.qb.DocType("Cost Table")
	empty = Coalesce(ct.supplier, "") == ""

	for doctype, fields in (
		("Transportation", ("transporter",)),
		("Custom Clearance", ("transporter_name", "broker_name")),
	):
		parent = frappe.qb.DocType(doctype)
		rows = (
			frappe.qb.from_(ct)
			.join(parent)
			.on(parent.name == ct.parent)
			.select(ct.name, *[parent[f] for f in fields])
			.where((ct.parenttype == doctype) & (ct.parentfield == "cost_table") & empty)
			.run(as_dict=True)
		)
		for r in rows:
			supplier = next((r[f] for f in fields if r[f]), None)
			if supplier:
				frappe.db.set_value("Cost Table", r.name, "supplier", supplier, update_modified=False)

	origin = frappe.qb.DocType("Cost Table").as_("origin")
	copies = (
		frappe.qb.from_(ct)
		.join(origin)
		.on(origin.ref_id == ct.name)
		.select(ct.name, origin.supplier)
		.where(
			(ct.parenttype == "Operations")
			& empty
			& origin.parenttype.isin(["Transportation", "Custom Clearance"])
			& (Coalesce(origin.supplier, "") != "")
		)
		.run(as_dict=True)
	)
	for r in copies:
		frappe.db.set_value("Cost Table", r.name, "supplier", r.supplier, update_modified=False)
