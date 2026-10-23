# Copyright (c) 2026, DVNKS Systems and contributors
"""B7's message names the job's Services, not a tick-box: Customs Clearance
is now a service on the job (M-05). Replaced only while it is still a text
this app seeded, so a site's own wording stays."""

import frappe

from forwarding.patches.v1_0.seed_job_banner_rules import RULES

SEEDED_MESSAGES = (
	"Import job with no Custom Clearance yet",
	"Customs Clearance is ticked but no Custom Clearance has been created yet",
)


def execute():
	message = next(r for r in RULES if r["rule_code"] == "B7")["message_template"]
	for name in frappe.get_all(
		"Job Banner Rule",
		filters={"condition_key": "customs_missing", "message_template": ["in", SEEDED_MESSAGES]},
		pluck="name",
	):
		frappe.db.set_value("Job Banner Rule", name, "message_template", message, update_modified=False)
	frappe.cache.delete_keys("job_360")
