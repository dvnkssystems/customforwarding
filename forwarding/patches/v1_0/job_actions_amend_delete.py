# Copyright (c) 2026, DVNKS Systems and contributors
"""Job 360: More gets Amend and Delete job (Round 2: R2-09, R2-11).

A Custom UI Dashboard's actions list is the whole list (an action it leaves
out is hidden), so the two new actions are added to each dashboard that
drives the job page: Amend right after Cancel job, Delete job right after
Audit log, each in the group its neighbour sits in (else "more"). An action
the record already names -- shown or hidden -- is left as it is, so running
this again changes nothing.
"""

import json

import frappe

from forwarding.api.ui_config import DASHBOARD, PAGES

NEW_ACTIONS = (
	# (key, the action it follows)
	("amend", "cancel"),
	("delete", "audit_log"),
)
SPEC = {a["key"]: a for a in PAGES["job_360"]["actions"]}


def add_actions(props):
	"""props with the missing actions added; None when nothing changes."""
	actions = props.get("actions") if isinstance(props, dict) else None
	if not isinstance(actions, list):
		return None
	out = list(actions)
	keys = [a.get("key") if isinstance(a, dict) else None for a in out]
	changed = False
	for key, after in NEW_ACTIONS:
		if key in keys:
			continue
		spec = SPEC[key]
		at = keys.index(after) + 1 if after in keys else len(out)
		neighbour = out[at - 1] if after in keys and isinstance(out[at - 1], dict) else {}
		entry = {
			"key": key,
			"label": spec["label"],
			"group": neighbour.get("group", spec["group"]) if neighbour else spec["group"],
			"icon": spec["icon"],
		}
		out.insert(at, entry)
		keys.insert(at, key)
		changed = True
	return {**props, "actions": out} if changed else None


def execute():
	if "custom_ui" not in frappe.get_installed_apps():
		return
	spec_name = PAGES["job_360"]["dashboard"]
	for name, raw in frappe.get_all(DASHBOARD, fields=["name", "entity_props"], as_list=True):
		try:
			props = json.loads(raw or "{}")
		except ValueError:
			continue
		if not isinstance(props, dict):
			continue
		if props.get("freight_page") != "job_360" and name != spec_name:
			continue
		new = add_actions(props)
		if new is not None:
			frappe.db.set_value(DASHBOARD, name, "entity_props", json.dumps(new, indent=1), update_modified=False)
	frappe.cache.delete_keys("ui_config:")
