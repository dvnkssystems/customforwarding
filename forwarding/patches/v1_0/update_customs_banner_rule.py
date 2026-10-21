# Copyright (c) 2026, DVNKS Systems and contributors
"""B7 now fires when Customs Clearance is ticked on the job and no Custom
Clearance exists (C8), not on every import job. Its message is replaced only
while it is still the text first seeded, so a site's own wording stays."""

import frappe

from forwarding.patches.v1_0.seed_job_banner_rules import RULES

ORIGINAL_MESSAGE = "Import job with no Custom Clearance yet"


def execute():
	seed = next(r for r in RULES if r["rule_code"] == "B7")
	for name in frappe.get_all(
		"Job Banner Rule",
		filters={"condition_key": "customs_missing", "message_template": ORIGINAL_MESSAGE},
		pluck="name",
	):
		frappe.db.set_value(
			"Job Banner Rule", name, "message_template", seed["message_template"], update_modified=False
		)
	frappe.cache.delete_keys("job_360")
