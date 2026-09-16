# Copyright (c) 2026, DVNKS Systems and contributors
"""Fill Operations.operation_id with the job number on existing jobs.

Operation ID became read-only and is now set from the job name on save, so
jobs saved before that carry a blank one.
"""

import frappe


def execute():
	frappe.db.sql(
		"""
		update `tabOperations`
		set operation_id = name
		where ifnull(operation_id, '') = ''
		"""
	)
