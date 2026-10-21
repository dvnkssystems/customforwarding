# Copyright (c) 2026, DVNKS Systems and contributors
"""Give open export jobs their default cut-off rows.

A new export job gets its mode's cut-off milestones on insert
(Operations.set_default_cutoffs); jobs made before that have none. Rows are
added undated, straight into the child table, so the job is not saved
(a full save would run today's validations on old data). Jobs that are
cancelled, finished, or already have any cut-off are left alone. Idempotent.
"""

import frappe
from frappe.utils import cstr

from forwarding.banners import FINISHED
from forwarding.forwarding.doctype.operations.operations import default_cutoff_milestones


def execute():
	jobs = frappe.get_all(
		"Operations",
		filters={"job_type": "Export", "docstatus": ["<", 2]},
		fields=["name", "mode_of_shipment", "destination_country", "port_of_destination", "operations_status"],
	)
	with_cutoffs = set(frappe.get_all("Job Cutoff", filters={"parenttype": "Operations"}, pluck="parent", distinct=True))
	for job in jobs:
		if job.name in with_cutoffs or cstr(job.operations_status).lower() in FINISHED:
			continue
		country = job.destination_country or (
			frappe.db.get_value("Port", job.port_of_destination, "country") if job.port_of_destination else None
		)
		for idx, milestone in enumerate(default_cutoff_milestones(job.mode_of_shipment, country), 1):
			frappe.get_doc(
				{
					"doctype": "Job Cutoff",
					"parent": job.name,
					"parenttype": "Operations",
					"parentfield": "cutoffs",
					"idx": idx,
					"milestone": milestone,
				}
			).db_insert()
	frappe.cache.delete_keys("job_360")
