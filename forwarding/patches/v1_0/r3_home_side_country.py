"""Back-fill the Saudi side of existing jobs (R3-05).

An Import job's Destination Country and an Export job's Loading Country are
Saudi Arabia. New jobs get it from the form and on save; this sets it on the
jobs saved before, so opening one does not change it (and mark it unsaved).
Cancelled jobs are left as they were.
"""

import frappe

HOME_COUNTRY = "Saudi Arabia"
def execute():
	if not frappe.db.exists("Territory", HOME_COUNTRY):
		return
	args = {"country": HOME_COUNTRY}
	frappe.db.sql(
		"""update `tabOperations` set destination_country = %(country)s
		where job_type = 'Import' and docstatus < 2
		and ifnull(destination_country, '') != %(country)s""",
		args,
	)
	frappe.db.sql(
		"""update `tabOperations` set loading_country = %(country)s
		where job_type = 'Export' and docstatus < 2
		and ifnull(loading_country, '') != %(country)s""",
		args,
	)
