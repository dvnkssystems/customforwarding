# Copyright (c) 2026, DVNKS Systems and contributors
"""Job Delivery Note off (ONE Freight, 2 Nov, item 15): it is the same
document as the Proof of Delivery, which the job's print button now opens.
A print format's Disabled flag is kept as it is when the file syncs, so it is
set here. The file stays, so the format can be switched back on.
"""

import frappe


def execute():
	if frappe.db.exists("Print Format", "Job Delivery Note"):
		frappe.db.set_value("Print Format", "Job Delivery Note", "disabled", 1, update_modified=False)
