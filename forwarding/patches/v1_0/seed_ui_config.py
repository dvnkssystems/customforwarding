# Copyright (c) 2026, DVNKS Systems and contributors
"""Seed the custom_ui records the Freight LCS pages read their layout from.

Custom UI Dashboards "Job 360", "Customer 360", "Supplier 360" and
"Freight Home", and the Custom UI Wizard Layout "New Job", each written
from the built-in defaults in forwarding.api.ui_config so the pages look
exactly as before until someone edits them.

custom_ui ships no client's records (its test_no_tenant_fixtures), so they
are seeded from this app, and as records rather than fixtures: a record is
only inserted when missing, so an admin's edits are never overwritten, and a
record deleted on purpose comes back only if someone reruns the patch.
"""

import json

import frappe

from forwarding.api.ui_config import DASHBOARD, PAGES, WIZARD_LAYOUT, WIZARDS

PAGE_SUBTITLES = {
	"job_360": "Tabs, KPI tiles and actions on the Job 360 page",
	"customer_360": "Tabs, KPI tiles and actions on the Customer 360 page",
	"supplier_360": "Tabs, KPI tiles and actions on the Supplier 360 page",
	"home": "Sections on the Freight LCS home page",
}


def execute():
	if "custom_ui" not in frappe.get_installed_apps():
		return
	for page in PAGES:
		seed_dashboard(page)
	for name in WIZARDS:
		seed_wizard(name)
	frappe.cache.delete_keys("ui_config:")


def dashboard_doc(page):
	spec = PAGES[page]
	doc = {
		"doctype": DASHBOARD,
		"dashboard_name": spec["dashboard"],
		"title": spec["title"],
		"subtitle": PAGE_SUBTITLES[page],
		"is_active": 1,
	}
	if page == "home":
		props = {
			"freight_page": page,
			"sections": [{"key": s["key"], "label": s["label"], "hidden": 0} for s in spec["sections"]],
		}
	else:
		doc.update(
			{
				"entity_doctype": spec["entity_doctype"],
				"entity_layout": "Stacked",
				# A record opens on exactly one dashboard; leave the flag to
				# an existing claimant (custom_ui refuses a second one).
				"is_default_record_view": 0 if _record_view_taken(spec["entity_doctype"]) else 1,
				"tabs": [
					{
						"tab_group": "Entity",
						"tab_key": t["key"],
						"label": t["label"],
						"icon": t["icon"],
						"is_default": t["is_default"],
						"sort_order": (i + 1) * 10,
					}
					for i, t in enumerate(spec["tabs"])
				],
			}
		)
		props = {
			"freight_page": page,
			"tiles": [{"key": t["key"], "label": t["label"], "tab": t["tab"]} for t in spec["tiles"]],
			"action_groups": [{"key": g["key"], "label": g["label"]} for g in spec["groups"]],
			"actions": [
				{"key": a["key"], "label": a["label"], "group": a["group"], "icon": a["icon"]}
				for a in spec["actions"]
			],
			"banners": dict(spec["banners"]),
		}
	doc["entity_props"] = json.dumps(props, indent=1)
	return doc


def _record_view_taken(doctype):
	return bool(
		frappe.db.exists(DASHBOARD, {"entity_doctype": doctype, "is_default_record_view": 1, "is_active": 1})
	)


def seed_dashboard(page):
	if frappe.db.exists(DASHBOARD, PAGES[page]["dashboard"]):
		return
	frappe.get_doc(dashboard_doc(page)).insert(ignore_permissions=True)


def wizard_doc(name):
	spec = WIZARDS[name]
	meta = frappe.get_meta(spec["target_doctype"])
	settings = {
		"save_from_step": spec["save_from_step"],
		"steps": [
			{"key": s["key"], "label": s["label"], "hint": s["hint"], "icon": s["icon"]} for s in spec["steps"]
		],
	}
	return {
		"doctype": WIZARD_LAYOUT,
		"wizard": name,
		"is_active": 1,
		"description": json.dumps(settings, indent=1),
		"fields": [
			{
				"section": step["key"],
				"target_doctype": spec["target_doctype"],
				"fieldname": fieldname,
				# Blank means the DocType's own label; only the renamed ones
				# are written, so a later relabel on the DocType still shows.
				"label": spec["labels"].get(fieldname),
			}
			for step in spec["steps"]
			for fieldname in step["fields"]
			if meta.get_field(fieldname)
		],
	}


def seed_wizard(name):
	if frappe.db.exists(WIZARD_LAYOUT, {"wizard": name}):
		return
	frappe.get_doc(wizard_doc(name)).insert(ignore_permissions=True)
