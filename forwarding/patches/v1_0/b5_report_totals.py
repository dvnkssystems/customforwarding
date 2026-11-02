# Copyright (c) 2026, DVNKS Systems and contributors
"""Operations & Invoice Details gets Frappe's Total row (A-41), which the app
keeps in view while the report scrolls. Its report JSON says the same for a
fresh install.

The two Estimated Job reports keep add_total_row off: their rows nest (a job,
then its cost rows) and they append a Total row of their own, so Frappe's
would count every figure twice. The app treats a last row reading "Total" as
the report's total.
"""

import frappe


def execute():
	if frappe.db.exists("Report", "Operations and Invoice Details"):
		frappe.db.set_value("Report", "Operations and Invoice Details", "add_total_row", 1, update_modified=False)
