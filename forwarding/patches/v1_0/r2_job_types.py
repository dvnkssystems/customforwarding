# Copyright (c) 2026, DVNKS Systems and contributors
"""Job Type list (M-14, awaiting Simran's confirmation).

* LAND TRANSPORT is a mode, not a job type: it becomes Domestic, for local
  jobs. rename_doc (merge=False) updates every link to it. Its abbreviation,
  which goes into job numbers, becomes DM; no job used LAND TRANSPORT on the
  local site, so no existing job number reads differently.
* Others is deleted when nothing links to it. A site where jobs still use it
  keeps it, and the patch says how many.

To undo the rename: frappe.rename_doc("Job Type", "Domestic", "LAND TRANSPORT").
"""

import frappe

OLD, NEW = "LAND TRANSPORT", "Domestic"
NEW_ABBR = "DM"


def execute():
	if frappe.db.exists("Job Type", OLD) and not frappe.db.exists("Job Type", NEW):
		frappe.rename_doc("Job Type", OLD, NEW, merge=False, force=True, show_alert=False)
	if frappe.db.exists("Job Type", NEW):
		frappe.db.set_value("Job Type", NEW, {"job_type": NEW, "abbreviation": NEW_ABBR}, update_modified=False)

	if frappe.db.exists("Job Type", "Others"):
		used = frappe.db.count("Operations", {"job_type": "Others"})
		if used:
			print(f"Job Type Others kept: {used} job(s) use it")
			return
		try:
			frappe.delete_doc("Job Type", "Others", ignore_permissions=True)
		except frappe.LinkExistsError:
			# Linked from something other than a job; leave it.
			frappe.clear_last_message()
			print("Job Type Others kept: other records link to it")
