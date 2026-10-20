# Copyright (c) 2026, DVNKS Systems and contributors
"""Job Banner Rule now has Applies To (Operations / Customer / Supplier).
Every rule that existed before was a Job 360 rule."""

import frappe


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	rule = frappe.qb.DocType("Job Banner Rule")
	(
		frappe.qb.update(rule)
		.set(rule.applies_to, "Operations")
		.where(rule.applies_to.isnull() | (rule.applies_to == ""))
		.run()
	)
