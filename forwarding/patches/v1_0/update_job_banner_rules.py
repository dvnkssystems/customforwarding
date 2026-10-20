# Copyright (c) 2026, DVNKS Systems and contributors
"""Give the seeded Job Banner Rules their worklist labels, and show their
dates as "19 Oct 2026" instead of the system format.

A message is only replaced while it is still the text first seeded, and a
label only filled in while empty, so nothing edited on a site is overwritten.
"""

import frappe

from forwarding.patches.v1_0.seed_job_banner_rules import RULES

# The B2 / B3 / B4 messages as first seeded, before format_date existed.
ORIGINAL_MESSAGES = {
	"B4": "{% set d = ctx.free_days_left %}{% if d < 0 %}Free time expired {{ -d }} day{{ 's' if d != -1 }} ago{% elif d == 0 %}Free time expires today{% else %}Free time expires in {{ d }} day{{ 's' if d != 1 }}{% endif %} ({{ frappe.utils.formatdate(doc.free_time_expiry) }})",
	"B2": "ETD was {{ frappe.utils.formatdate(doc.etd_date) }} but no ATD has been recorded",
	"B3": "ETA was {{ frappe.utils.formatdate(doc.eta_date) }} but no ATA has been recorded",
}


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	seeded = {r["rule_code"]: r for r in RULES}

	for rule in frappe.get_all("Job Banner Rule", fields=["name", "rule_code", "label", "message_template"]):
		seed = seeded.get(rule.rule_code)
		if not seed:
			continue
		values = {}
		if not rule.label and seed.get("label"):
			values["label"] = seed["label"]
		original = ORIGINAL_MESSAGES.get(rule.rule_code)
		if original and rule.message_template == original:
			values["message_template"] = seed["message_template"]
		if values:
			frappe.db.set_value("Job Banner Rule", rule.name, values, update_modified=False)

	frappe.cache.delete_keys("job_360:")
