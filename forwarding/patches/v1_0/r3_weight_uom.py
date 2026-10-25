# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-31): one Kg, and every job's weights in a weight unit.

* UOM "KGS" is merged into "Kg" (Rename > Merge), so every record that used
  KGS -- items, invoice rows, jobs -- now says Kg.
* A job with no Weight UOM gets Kg, the new default (its weights were always
  entered in kg: the package totals are labelled so).

Running it again changes nothing.
"""

import frappe


def execute():
	if frappe.db.exists("UOM", "KGS") and frappe.db.exists("UOM", "Kg"):
		frappe.rename_doc("UOM", "KGS", "Kg", merge=True, force=True, show_alert=False)
		print("R3-31: merged UOM KGS into Kg")
	if frappe.db.exists("UOM", "Kg"):
		jobs = frappe.get_all("Operations", filters=[["weight_uom", "is", "not set"]], pluck="name")
		for name in jobs:
			frappe.db.set_value("Operations", name, "weight_uom", "Kg", update_modified=False)
		print(f"R3-31: Weight UOM set to Kg on {len(jobs)} jobs")
