# Copyright (c) 2026, DVNKS Systems and contributors
"""Job Type list (M-14 withdrawn): LAND TRANSPORT and Others stay.

r2_job_types renamed LAND TRANSPORT to Domestic (DM) and deleted Others.
Where it did, Domestic is renamed back (rename_doc, merge=False, so every link
follows) with its old abbreviation LT, and Others (OT) is created again.
"""

import frappe

DOMESTIC = "Domestic"
LAND, LAND_ABBR = "LAND TRANSPORT", "LT"
OTHERS, OTHERS_ABBR = "Others", "OT"


def execute():
	if frappe.db.exists("Job Type", DOMESTIC) and not frappe.db.exists("Job Type", LAND):
		frappe.rename_doc("Job Type", DOMESTIC, LAND, merge=False, force=True, show_alert=False)
		frappe.db.set_value(
			"Job Type", LAND, {"job_type": LAND, "abbreviation": LAND_ABBR}, update_modified=False
		)

	if not frappe.db.exists("Job Type", OTHERS):
		frappe.get_doc({"doctype": "Job Type", "job_type": OTHERS, "abbreviation": OTHERS_ABBR}).insert(
			ignore_permissions=True
		)
