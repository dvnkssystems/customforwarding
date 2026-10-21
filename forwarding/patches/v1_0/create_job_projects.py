# Copyright (c) 2026, DVNKS Systems and contributors
"""Give every live job the Project its invoices expect.

The site's invoice client scripts set `project` to the job's name, but only a
desk client script ever created that Project — so jobs saved from the app or
seeded by script had none, and raising a Sales Invoice from them failed with
"Could not find Project". New jobs get one on save (Operations.ensure_project);
this backfills the rest. Safe to rerun: a job whose Project exists is skipped.
"""

import frappe


def execute():
	default_company = frappe.db.get_single_value("Global Defaults", "default_company")
	for name in frappe.get_all("Operations", filters={"docstatus": ["<", 2]}, pluck="name"):
		doc = frappe.get_doc("Operations", name)
		if not doc.company:
			doc.company = default_company
		doc.ensure_project()
