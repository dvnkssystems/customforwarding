# Copyright (c) 2026, DVNKS Systems and contributors
"""Seed the Job 360 banner rules B1-B8.

A rule is only inserted when its code is missing, so wording, priority or
colour edited on a site is never overwritten, and a rule deleted on purpose
comes back only if someone reruns the patch by hand.
"""

import frappe

RULES = [
	{
		"rule_code": "B8",
		"label": "On hold",
		"priority": 10,
		"condition_key": "credit_hold",
		"action": "request_override",
		"colour": "critical",
		"show_on_worklist": 1,
		"message_template": "Job is on hold{% if doc.hold_reason %}: {{ doc.hold_reason }}{% endif %}",
	},
	{
		"rule_code": "B6",
		"label": "Invoices overdue",
		"priority": 20,
		"condition_key": "invoice_overdue",
		"action": "view_invoice",
		"colour": "critical",
		"show_on_worklist": 1,
		"message_template": "{{ ctx.overdue_invoices|length }} invoice{{ 's are' if ctx.overdue_invoices|length != 1 else ' is' }} overdue: {{ ctx.overdue_invoices|join(', ') }}",
	},
	{
		"rule_code": "B5",
		"label": "Not invoiced",
		"priority": 30,
		"condition_key": "not_invoiced",
		"action": "create_sales_invoice",
		"colour": "critical",
		"show_on_worklist": 1,
		"message_template": "Job is {{ doc.operations_status }} but has not been invoiced",
	},
	{
		"rule_code": "B4",
		"label": "Free time expiring",
		"priority": 40,
		"condition_key": "free_time_expiring",
		"action": "view_milestones",
		"colour": "warning",
		"show_on_worklist": 1,
		"message_template": "{% set d = ctx.free_days_left %}{% if d < 0 %}Free time expired {{ -d }} day{{ 's' if d != -1 }} ago{% elif d == 0 %}Free time expires today{% else %}Free time expires in {{ d }} day{{ 's' if d != 1 }}{% endif %} ({{ format_date(doc.free_time_expiry) }})",
	},
	{
		"rule_code": "B2",
		"label": "ATD missing",
		"priority": 50,
		"condition_key": "atd_missing",
		"action": "record_atd",
		"colour": "warning",
		"show_on_worklist": 1,
		"message_template": "ETD was {{ format_date(doc.etd_date) }} but no ATD has been recorded",
	},
	{
		"rule_code": "B3",
		"label": "ATA missing",
		"priority": 60,
		"condition_key": "ata_missing",
		"action": "record_ata",
		"colour": "warning",
		"show_on_worklist": 1,
		"message_template": "ETA was {{ format_date(doc.eta_date) }} but no ATA has been recorded",
	},
	{
		"rule_code": "B1",
		"label": "Documents pending",
		"priority": 70,
		"condition_key": "docs_pending",
		"action": "upload_documents",
		"colour": "warning",
		"show_on_worklist": 1,
		"message_template": "{% set n = ctx.docs_total - ctx.docs_received %}{{ n }} document{{ 's' if n != 1 }} awaiting: {{ ctx.pending_documents|join(', ') }}",
	},
	{
		"rule_code": "B7",
		"label": "Customs not started",
		"priority": 80,
		"condition_key": "customs_missing",
		"action": "create_custom_clearance",
		"colour": "info",
		"show_on_worklist": 0,
		"message_template": "Import job with no Custom Clearance yet",
	},
]


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	for rule in RULES:
		if frappe.db.exists("Job Banner Rule", rule["rule_code"]):
			continue
		frappe.get_doc({"doctype": "Job Banner Rule", "enabled": 1, **rule}).insert(ignore_permissions=True)
