# Copyright (c) 2026, DVNKS Systems and contributors
"""A "Users" entry in the app menu, under Setup, for admins only (ONE Freight,
12 Nov). It opens the app's /users screen (forwarding.user_admin).

custom_ui's Custom UI Sidebar Item records are site data, so the entry is
added here; a site without custom_ui or without a Setup group skips it.
Idempotent: an existing entry for /users is left as it is.
"""

import frappe

from forwarding.patches.v1_0.b5_sidebar_cleanup import ITEM, top_group

ROUTE = "/users"
NAME = "FF Users"


def execute():
	if not frappe.db.exists("DocType", ITEM) or frappe.db.exists(ITEM, NAME) or frappe.db.exists(ITEM, {"route": ROUTE}):
		return
	group = top_group("Setup") or top_group("Masters")
	if not group:
		return
	orders = frappe.get_all(ITEM, filters={"parent_item": group}, pluck="sort_order")
	frappe.get_doc(
		{
			"doctype": ITEM,
			"name": NAME,
			"item_label": "Users",
			"item_type": "Page",
			"icon": "users",
			"page_route": ROUTE,
			"parent_item": group,
			"sort_order": max([0, *(o or 0 for o in orders)]) + 1,
			"is_active": 1,
			"roles": [{"role": "System Manager"}],
		}
	).insert(ignore_permissions=True)
