# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-52): free time counted from the right event.

Every job not cancelled gets its Free Time Expires worked out again with
Operations.free_time_start: an import from its ATA (no longer the ETA), an
export from its Container Pickup cut-off. A job whose start has not happened
yet has no expiry, so no "free time expires" alert fires early. Running it
again changes nothing.
"""

import frappe


def execute():
	changed = 0
	for name in frappe.get_all("Operations", filters={"docstatus": ["<", 2]}, pluck="name"):
		job = frappe.get_doc("Operations", name)
		before = job.free_time_expiry
		job.set_free_time_expiry()
		if str(before or "") != str(job.free_time_expiry or ""):
			frappe.db.set_value("Operations", name, "free_time_expiry", job.free_time_expiry, update_modified=False)
			changed += 1
	print(f"R3-52: Free Time Expires changed on {changed} jobs")
