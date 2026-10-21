# Copyright (c) 2026, DVNKS Systems and contributors
"""Custom Clearance owns the customs declaration and D.O details (D3).

The job's Documents & D.O section repeated Bayan No. / Date, D.O No. / Date,
Clearance Date and the two duty amounts, which the job form now hides. Copy
each value a job holds onto its Custom Clearance where the clearance has none
yet, so nothing typed on the job is lost. A clearance's own value is never
overwritten, and running again changes nothing.
"""

import frappe

# Operations field -> Custom Clearance field
FIELD_MAP = {
	"bayan_no": "bayyan_number",
	"bayan_date": "bayyan_date",
	"do_no": "do_number",
	"do_date": "do_date",
	"clearance_date": "clearance_date",
	"duty_amount_company": "duty_amount_company",
	"duty_amount_client": "duty_amount_client",
}


def execute():
	frappe.reload_doc("forwarding", "doctype", "custom_clearance")
	counts = copy_job_fields()
	print("Custom Clearance fields copied from jobs: {0}".format(counts))


def linked_clearances(jobs=None):
	"""(clearance, job) pairs: clearances naming the job, and the job's
	custom_clearance_id where that names one."""
	filters = {"operations": ["in", jobs]} if jobs else {"operations": ["is", "set"]}
	pairs = {(r.name, r.operations) for r in frappe.get_all("Custom Clearance", filters=filters, fields=["name", "operations"])}

	job_filters = {"custom_clearance_id": ["is", "set"]}
	if jobs:
		job_filters["name"] = ["in", jobs]
	for r in frappe.get_all("Operations", filters=job_filters, fields=["name", "custom_clearance_id"]):
		if frappe.db.exists("Custom Clearance", r.custom_clearance_id):
			pairs.add((r.custom_clearance_id, r.name))
	return sorted(pairs)


def _empty(value):
	return value in (None, "", 0, 0.0)


def copy_job_fields(jobs=None):
	"""Copy the job's clearance values onto its linked clearances' empty fields.

	Returns {"clearances": updated clearances, "fields": values copied}."""
	clearances = values = 0
	for cc_name, job in linked_clearances(jobs):
		source = frappe.db.get_value("Operations", job, list(FIELD_MAP), as_dict=True)
		if not source:
			continue
		target = frappe.db.get_value("Custom Clearance", cc_name, list(FIELD_MAP.values()), as_dict=True)
		updates = {
			cc_field: source[job_field]
			for job_field, cc_field in FIELD_MAP.items()
			if not _empty(source[job_field]) and _empty(target[cc_field])
		}
		if updates:
			frappe.db.set_value("Custom Clearance", cc_name, updates, update_modified=False)
			clearances += 1
			values += len(updates)
	return {"clearances": clearances, "fields": values}
