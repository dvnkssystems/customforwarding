# Copyright (c) 2026, DVNKS Systems and contributors
"""Seed the Phase 2 party banners (spec §6.2, provisional): C5 on Customer
360 and S4 / S6 on Supplier 360.

The other §6.2 rules are already seeded (C1-C3, S1) or wait for later work:
C4 and the spec's S2 / S3 need Party Document, S5 the Vehicle transporter
link. Those spec codes S2 / S3 are not used here because the site's S2 / S3
are the unbilled-services and on-hold banners.

Like seed_party_banner_rules, a rule is only inserted when its code is
missing, so anything edited on a site is never overwritten.
"""

import frappe

RULES = [
	{
		"rule_code": "C5",
		"applies_to": "Customer",
		"label": "Jobs delivered, not invoiced",
		"priority": 25,
		"condition_key": "job_not_invoiced",
		"action": "view_jobs",
		"colour": "critical",
		"message_template": (
			"{% set rows = ctx.not_invoiced_jobs %}"
			"{% if rows|length == 1 %}"
			"{{ _('Job {0} is delivered but not invoiced').format(rows[0].name) }}"
			"{% else %}"
			"{{ _('{0} jobs delivered but not invoiced').format(rows|length) }}"
			"{% endif %}"
		),
	},
	{
		"rule_code": "S4",
		"applies_to": "Supplier",
		"label": "Rates expiring",
		"priority": 40,
		"condition_key": "rate_expiring",
		"action": "view_rates",
		"colour": "warning",
		"message_template": (
			"{% set rows = ctx.expiring_rates %}"
			"{% if rows|length == 1 %}"
			"{{ _('Rate for {0} ends {1}').format(rows[0].item_code, format_date(rows[0].valid_upto)) }}"
			"{% else %}"
			"{{ _('{0} rates end within {1} days, first {2}').format(rows|length, ctx.rate_expiry_days, format_date(rows[0].valid_upto)) }}"
			"{% endif %}"
		),
	},
	{
		"rule_code": "S6",
		"applies_to": "Supplier",
		"label": "Jobs over estimate",
		"priority": 50,
		"condition_key": "over_estimate",
		"action": "view_jobs",
		"colour": "warning",
		"message_template": (
			"{% set n = ctx.jobs_over|length %}"
			"{% if n == 1 %}"
			"{{ _('Job {0} invoiced {1}% over estimate').format(ctx.jobs_over[0].job, flt(ctx.jobs_over[0].variance_pct, 1)) }}"
			"{% else %}"
			"{{ _('{0} jobs invoiced more than {1}% over estimate').format(n, flt(ctx.cost_variance.threshold, 1)) }}"
			"{% endif %}"
		),
	},
]


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	for rule in RULES:
		if frappe.db.exists("Job Banner Rule", rule["rule_code"]):
			continue
		frappe.get_doc({"doctype": "Job Banner Rule", "enabled": 1, **rule}).insert(ignore_permissions=True)
