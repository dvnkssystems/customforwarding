# Copyright (c) 2026, DVNKS Systems and contributors
"""KANOO LOGISTICS is a handling agent as well as a shipping line (Simran,
2 Nov).

Its Shipping Line record and tick are Royal Eagle's own data and stay; only
the Handling Agent tick is added. Skipped where the supplier is missing.
"""

import frappe


def execute():
	if frappe.db.exists("Supplier", "KANOO LOGISTICS"):
		frappe.db.set_value("Supplier", "KANOO LOGISTICS", "is_handling_agent", 1, update_modified=False)
