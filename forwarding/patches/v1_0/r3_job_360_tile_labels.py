# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-32, R3-35): Job 360 tile labels on the site's Custom UI
Dashboard "Job 360" follow the new defaults -- "Service orders" (was
"Linked services") and "Estimate: cost / selling" (was "Cost vs revenue").
Only a label still at its old default is changed; one renamed on the site is
kept. Running it again changes nothing.
"""

import json

import frappe

RENAMES = {
	("services", "Linked services"): "Service orders",
	("cost_revenue", "Cost vs revenue"): "Estimate: cost / selling",
}


def execute():
	if not frappe.db.exists("DocType", "Custom UI Dashboard"):
		return
	for row in frappe.get_all("Custom UI Dashboard", fields=["name", "entity_props"]):
		try:
			props = json.loads(row.entity_props or "{}")
		except ValueError:
			continue
		if not isinstance(props, dict) or props.get("freight_page") != "job_360":
			continue
		changed = False
		for tile in props.get("tiles") or []:
			new = RENAMES.get((tile.get("key"), tile.get("label")))
			if new:
				tile["label"] = new
				changed = True
		if changed:
			frappe.db.set_value(
				"Custom UI Dashboard", row.name, "entity_props", json.dumps(props, indent=1), update_modified=False
			)
	frappe.cache.delete_keys("ui_config:")
