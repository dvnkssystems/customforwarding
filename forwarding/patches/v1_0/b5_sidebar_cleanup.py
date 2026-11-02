# Copyright (c) 2026, DVNKS Systems and contributors
"""Left menu clean-up (A-46). Menu entries only: no master record is merged
or deleted, and a hidden entry is switched off (is_active 0), not removed.

- Masters (Ports & Terminals, Shipment Setup, Charges & Accounting) become
  one "Setup" group at the bottom; the app opens it closed (src/lib/sidebar.js
  isCollapsedGroup), so the menu shows transactions and reports.
- Dunning (Collections) goes.
- Seaports, Airports and Ports become the one Ports entry (the Port list has
  a Sea / Air filter in the app); Trucks and Vehicles become Vehicles.
- Customers moves from Transport & Warehousing to Parties.
- Stock Entries, Lorry Receipt (Sales Order) and Purchase Order are hidden.

The entries are custom_ui's Custom UI Sidebar Item records, which no app
ships, so they are found by what they open (target DocType) and their group's
label rather than by record name; a site without one simply skips it.
"""

import frappe

ITEM = "Custom UI Sidebar Item"
HIDE_DOCTYPES = ["Dunning", "Freight Seaport", "Freight Airport", "Freight Truck", "Stock Entry", "Purchase Order"]


def execute():
	if not frappe.db.exists("DocType", ITEM):
		return
	setup_group()
	for doctype in HIDE_DOCTYPES:
		for name in links(doctype):
			frappe.db.set_value(ITEM, name, "is_active", 0)
	# Lorry Receipt is a Sales Order entry; any other Sales Order entry stays.
	for name in links("Sales Order", item_label="Lorry Receipt"):
		frappe.db.set_value(ITEM, name, "is_active", 0)
	for name in links("Port"):
		frappe.db.set_value(ITEM, name, "item_label", "Ports")
	for name in links("Vehicle"):
		frappe.db.set_value(ITEM, name, "item_label", "Vehicles")
	parties = top_group("Parties")
	if parties:
		for name in links("Customer"):
			frappe.db.set_value(ITEM, name, {"parent_item": parties, "sort_order": 1})


def links(doctype, **filters):
	return frappe.get_all(
		ITEM, filters={"item_type": "Link", "target_doctype": doctype, "is_active": 1, **filters}, pluck="name"
	)


def top_group(label):
	"""An active top-level Group by its label ("FF Parties" on the sites
	seeded so far)."""
	for name in frappe.get_all(
		ITEM,
		filters={"item_type": "Group", "item_label": label, "is_active": 1},
		or_filters={"parent_item": ["is", "not set"]},
		pluck="name",
		order_by="sort_order asc",
	):
		return name
	return None


def setup_group():
	"""Masters → Setup, last in the menu."""
	group = top_group("Masters") or top_group("Setup")
	if not group:
		return
	orders = frappe.get_all(
		ITEM,
		filters={"is_active": 1, "name": ["!=", group]},
		or_filters={"parent_item": ["is", "not set"]},
		pluck="sort_order",
	)
	frappe.db.set_value(
		ITEM,
		group,
		{"item_label": "Setup", "icon": "settings", "sort_order": max([0, *(o or 0 for o in orders)]) + 1},
	)
