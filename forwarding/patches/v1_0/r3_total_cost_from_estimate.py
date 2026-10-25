# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-33): Total Cost is the estimate's, read-only.

custom_total_cost turns from Data into Currency (custom/operations.json, synced
after the patches). Its values are set first to each job's estimate cost (the
Cost Table rows' Cost added up), so none is NULL or text when the column type
changes -- MariaDB refuses that change otherwise. Running it again changes
nothing.
"""

import frappe
from frappe.utils import flt


def execute():
	if not frappe.db.has_column("Operations", "custom_total_cost"):
		return
	totals = {
		r.parent: flt(r.total)
		for r in frappe.db.sql(
			"""select parent, sum(cost) as total from `tabCost Table`
			where parenttype = %s and parentfield = %s group by parent""",
			("Operations", "cost_table"),
			as_dict=True,
		)
	}
	for name in frappe.get_all("Operations", pluck="name"):
		frappe.db.set_value("Operations", name, "custom_total_cost", totals.get(name, 0), update_modified=False)
