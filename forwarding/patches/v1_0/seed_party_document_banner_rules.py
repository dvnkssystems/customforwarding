# Copyright (c) 2026, DVNKS Systems and contributors
"""Seed the party document banners (spec §6.2 C4 and the spec's S2 / S3):
C4 / C6 on Customer 360, S7 / S8 on Supplier 360.

The site's S2 / S3 are the unbilled-services and on-hold banners, so the
supplier rules take S7 / S8, and the customer's expired rule C6. A document
row is either expiring or expired, never both, so at most one of each pair
names it.

Like seed_phase2_party_banner_rules, a rule is only inserted when its code is
missing, so anything edited on a site is never overwritten.
"""

import frappe

EXPIRING = (
	"{% set rows = ctx.expiring_documents %}"
	"{% if rows|length == 1 %}"
	"{{ _('{0} expires {1}').format(_(rows[0].document_type), format_date(rows[0].expiry_date)) }}"
	"{% else %}"
	"{{ _('{0} documents expire within {1} days').format(rows|length, ctx.document_expiry_days) }}"
	"{% endif %}"
)
EXPIRED = (
	"{% set rows = ctx.expired_documents %}"
	"{% if rows|length == 1 %}"
	"{{ _('{0} expired {1}').format(_(rows[0].document_type), format_date(rows[0].expiry_date)) }}"
	"{% else %}"
	"{{ _('{0} documents have expired').format(rows|length) }}"
	"{% endif %}"
)


def _rules(applies_to, expired_code, expired_priority, expiring_code, expiring_priority):
	return [
		{
			"rule_code": expired_code,
			"applies_to": applies_to,
			"label": "Documents expired",
			"priority": expired_priority,
			"condition_key": "party_document_expired",
			"action": "view_documents",
			"colour": "critical",
			"message_template": EXPIRED,
		},
		{
			"rule_code": expiring_code,
			"applies_to": applies_to,
			"label": "Documents expiring",
			"priority": expiring_priority,
			"condition_key": "party_document_expiring",
			"action": "view_documents",
			"colour": "warning",
			"message_template": EXPIRING,
		},
	]


RULES = _rules("Customer", "C6", 28, "C4", 35) + _rules("Supplier", "S8", 35, "S7", 45)


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	for rule in RULES:
		if frappe.db.exists("Job Banner Rule", rule["rule_code"]):
			continue
		frappe.get_doc({"doctype": "Job Banner Rule", "enabled": 1, **rule}).insert(ignore_permissions=True)
