# Copyright (c) 2026, DVNKS Systems and contributors
"""Seed Job Banner Rule B9, "Estimate missing" (M-02).

A draft job with no estimate row (Est. Selling above zero) shows "No estimate
entered yet" with an Add estimate button, and the Home worklist counts it.
Inserted only when B9 is missing, so a site's own wording is kept. Priority
90, last: every draft without an estimate has it, and it should not push the
operational prompts (documents, ATD / ATA) off the worklist.
"""

import frappe

RULE = {
	"rule_code": "B9",
	"applies_to": "Operations",
	"label": "Estimate missing",
	"priority": 90,
	"condition_key": "estimate_missing",
	"action": "add_estimate",
	"colour": "warning",
	"show_on_worklist": 1,
	"message_template": "No estimate entered yet",
}


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	if not frappe.db.exists("Job Banner Rule", RULE["rule_code"]):
		frappe.get_doc({"doctype": "Job Banner Rule", "enabled": 1, **RULE}).insert(ignore_permissions=True)
	frappe.cache.delete_keys("job_360")
