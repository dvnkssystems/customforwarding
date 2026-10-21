# Copyright (c) 2026, DVNKS Systems and contributors
"""Custom Clearance owns container clearance and clearance documents (D5).

The job's Container Clearance and Clearance Documents tables (now hidden on
the job) move to the job's Custom Clearance: each job's rows are copied onto
its clearance when the clearance has none of that table yet. The job's rows
are left in place. A job with rows but no clearance keeps them and is
counted, so they can be moved once a clearance is made (making one from the
job carries them over).
"""

import frappe

from forwarding.patches.v1_0.move_clearance_fields_to_custom_clearance import linked_clearances

TABLES = {
	"clearance_containers": "Operations Clearance Container",
	"clearance_documents": "Operations Clearance Document",
}


def execute():
	frappe.reload_doc("forwarding", "doctype", "custom_clearance")
	print("Clearance rows moved to Custom Clearance: {0}".format(copy_job_tables()))


def copy_job_tables(jobs=None):
	"""Returns {"copied_rows", "clearances", "skipped_has_rows", "jobs_without_clearance"}."""
	result = {"copied_rows": 0, "clearances": 0, "skipped_has_rows": 0, "jobs_without_clearance": 0}

	with_rows = set()
	for parentfield, child in TABLES.items():
		filters = {"parenttype": "Operations", "parentfield": parentfield}
		if jobs:
			filters["parent"] = ["in", jobs]
		with_rows.update(frappe.get_all(child, filters=filters, pluck="parent", distinct=True))
	if not with_rows:
		return result

	pairs = linked_clearances(sorted(with_rows))
	result["jobs_without_clearance"] = len(with_rows - {job for _cc, job in pairs})

	for cc_name, job in pairs:
		touched = False
		for parentfield, child in TABLES.items():
			rows = frappe.get_all(
				child,
				filters={"parenttype": "Operations", "parent": job, "parentfield": parentfield},
				fields=["*"],
				order_by="idx asc",
			)
			if not rows:
				continue
			if frappe.db.exists(child, {"parenttype": "Custom Clearance", "parent": cc_name, "parentfield": parentfield}):
				result["skipped_has_rows"] += 1
				continue
			for row in rows:
				new = frappe.new_doc(child)
				new.update({k: v for k, v in row.items() if k not in ("name", "parent", "parenttype", "parentfield", "creation", "modified", "owner", "modified_by")})
				new.update({"parent": cc_name, "parenttype": "Custom Clearance", "parentfield": parentfield, "idx": row.idx})
				new.db_insert()
				result["copied_rows"] += 1
			touched = True
		if touched:
			result["clearances"] += 1
	return result
