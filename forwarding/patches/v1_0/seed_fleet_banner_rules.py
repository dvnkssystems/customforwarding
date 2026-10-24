# Copyright (c) 2026, DVNKS Systems and contributors
"""Seed the fleet banners on Supplier 360 (spec §6.2 S5, and S9 for the
expired side): a transporter's vehicle insurance or driver licence expiring
within Party Alert Settings' Document Expiry Warning (Days), or expired.

A vehicle or driver is either expiring or expired, never both, so at most one
of the pair names it. Like seed_party_document_banner_rules, a rule is only
inserted when its code is missing, so anything edited on a site is never
overwritten.
"""

import frappe

# One row: "Vehicle ABC-123 insurance expires 12 Nov" / "Driver Ali licence
# expired 03 Oct"; several: a count.
EXPIRING = (
	"{% set rows = ctx.expiring_fleet %}"
	"{% if rows|length == 1 %}"
	"{% if rows[0].kind == 'Vehicle' %}"
	"{{ _('Vehicle {0} insurance expires {1}').format(rows[0].label, format_date(rows[0].date)) }}"
	"{% else %}"
	"{{ _('Driver {0} licence expires {1}').format(rows[0].label, format_date(rows[0].date)) }}"
	"{% endif %}"
	"{% else %}"
	"{{ _('{0} vehicle / driver documents expire within {1} days').format(rows|length, ctx.document_expiry_days) }}"
	"{% endif %}"
)
EXPIRED = (
	"{% set rows = ctx.expired_fleet %}"
	"{% if rows|length == 1 %}"
	"{% if rows[0].kind == 'Vehicle' %}"
	"{{ _('Vehicle {0} insurance expired {1}').format(rows[0].label, format_date(rows[0].date)) }}"
	"{% else %}"
	"{{ _('Driver {0} licence expired {1}').format(rows[0].label, format_date(rows[0].date)) }}"
	"{% endif %}"
	"{% else %}"
	"{{ _('{0} vehicle / driver documents have expired').format(rows|length) }}"
	"{% endif %}"
)

RULES = [
	{
		"rule_code": "S9",
		"applies_to": "Supplier",
		"label": "Fleet documents expired",
		"priority": 36,
		"condition_key": "fleet_expired",
		"action": "view_fleet",
		"colour": "critical",
		"message_template": EXPIRED,
	},
	{
		"rule_code": "S5",
		"applies_to": "Supplier",
		"label": "Fleet documents expiring",
		"priority": 46,
		"condition_key": "fleet_expiring",
		"action": "view_fleet",
		"colour": "warning",
		"message_template": EXPIRING,
	},
]


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	for rule in RULES:
		if frappe.db.exists("Job Banner Rule", rule["rule_code"]):
			continue
		frappe.get_doc({"doctype": "Job Banner Rule", "enabled": 1, **rule}).insert(ignore_permissions=True)
