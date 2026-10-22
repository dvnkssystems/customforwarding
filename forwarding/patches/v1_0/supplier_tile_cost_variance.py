# Copyright (c) 2026, DVNKS Systems and contributors
"""Supplier 360: the Open services tile becomes Cost variance (Phase 2 SU4).

In each Custom UI Dashboard whose entity_props drive the supplier page, the
tiles entry with key open_services is replaced in place by cost_variance,
keeping its position and hidden flag. Its label goes back to the default:
a renamed "Open services" would be wrong on the new tile. Nothing else in
the record changes. A record with no open_services entry is left alone, so
running this again does nothing.
"""

import json

import frappe

from forwarding.api.ui_config import DASHBOARD, PAGES

NEW_TILE = next(t for t in PAGES["supplier_360"]["tiles"] if t["key"] == "cost_variance")


def replace_tile(props):
	"""props with open_services swapped for cost_variance; None when there is
	nothing to change."""
	tiles = props.get("tiles") if isinstance(props, dict) else None
	if not isinstance(tiles, list):
		return None
	keys = [t.get("key") for t in tiles if isinstance(t, dict)]
	if "open_services" not in keys:
		return None
	out = []
	for tile in tiles:
		if isinstance(tile, dict) and tile.get("key") == "open_services":
			if "cost_variance" in keys:
				continue
			tile = {**NEW_TILE, "hidden": tile.get("hidden") or 0}
		out.append(tile)
	return {**props, "tiles": out}


def execute():
	if "custom_ui" not in frappe.get_installed_apps():
		return
	spec_name = PAGES["supplier_360"]["dashboard"]
	for name, raw in frappe.get_all(DASHBOARD, fields=["name", "entity_props"], as_list=True):
		try:
			props = json.loads(raw or "{}")
		except ValueError:
			continue
		if not isinstance(props, dict):
			continue
		if props.get("freight_page") != "supplier_360" and name != spec_name:
			continue
		new = replace_tile(props)
		if new is not None:
			frappe.db.set_value(DASHBOARD, name, "entity_props", json.dumps(new, indent=1), update_modified=False)
	frappe.cache.delete_keys("ui_config:")
