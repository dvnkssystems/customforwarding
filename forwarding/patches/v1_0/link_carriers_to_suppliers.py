# Copyright (c) 2026, DVNKS Systems and contributors
"""Fill Shipping Line.supplier and Carrier.supplier (Phase 2 spec §4) where a
Supplier has the same name, ignoring case and surrounding spaces, and tick
Is Shipping Line / Is Airline on it. A record already linked is left alone.

Prints the ones with no match, for mapping by hand. Writes with
db.set_value only: no record is saved, so nothing else runs.
"""

import json
import os

import frappe

from forwarding.carriers import ROLES


def _sync_supplier_customizations():
	"""Migrate syncs the app's custom/*.json after the post-model-sync
	patches; the Supplier role tick-boxes this patch sets come from
	custom/supplier.json, so sync that one file first."""
	from frappe.modules.utils import sync_customizations_for_doctype

	path = frappe.get_app_path("forwarding", "forwarding", "custom", "supplier.json")
	with open(path) as f:
		data = json.load(f)
	sync_customizations_for_doctype(data, os.path.dirname(path), "supplier.json")


def _key(name):
	return " ".join((name or "").split()).casefold()


def execute():
	for doctype in ROLES:
		frappe.reload_doc("forwarding", "doctype", frappe.scrub(doctype))
	_sync_supplier_customizations()

	suppliers = {}
	for row in frappe.get_all("Supplier", fields=["name", "supplier_name"], order_by="creation asc"):
		for key in {_key(row.name), _key(row.supplier_name)}:
			suppliers.setdefault(key, row.name)

	unmatched = {}
	for doctype, (role_field, _label) in ROLES.items():
		for name in frappe.get_all(doctype, filters={"supplier": ["is", "not set"]}, pluck="name", order_by="name asc"):
			supplier = suppliers.get(_key(name))
			if not supplier:
				unmatched.setdefault(doctype, []).append(name)
				continue
			frappe.db.set_value(doctype, name, "supplier", supplier, update_modified=False)
			frappe.db.set_value("Supplier", supplier, role_field, 1, update_modified=False)

	for doctype, names in unmatched.items():
		print(f"{doctype}: {len(names)} with no matching Supplier: {', '.join(names)}")
