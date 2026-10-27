# Copyright (c) 2026, DVNKS Systems and contributors
"""Older jobs get the services their service orders show (A-21).

New jobs fill Services from their scope (R3-23); a job saved before has
orders without the service: 07014 holds only Air Freight Import but has
TRIA2607014 and CRIA2607014, so the page read "Service orders 0 of 1". For
each live Transportation / Custom Clearance / Freight whose service type the
job's Services lack, the best-fitting code for the job's mode and type is
added (as a new job would get it), and its tick-box set. Cancelled jobs are
left alone; running it again adds nothing.
"""

import frappe

from forwarding import services


def best_code(service_type, mode_of_shipment, job_type):
	rows = frappe.get_all(
		"Freight Activity Code",
		filters={"is_hidden": 0, "service_type": service_type},
		fields=["name", "mode", "job_type"],
		order_by="name asc",
	)
	mode = services.code_mode(mode_of_shipment)
	fits = [r for r in rows if not services.code_problem(r.name, mode_of_shipment, job_type, None)]
	fits.sort(
		key=lambda r: (
			0 if job_type and r.job_type == job_type else 1,
			0 if mode and r.mode == mode else 1,
			r.name,
		)
	)
	return fits[0].name if fits else None


def execute():
	jobs = frappe.get_all("Operations", filters={"docstatus": ["<", 2]}, pluck="name")
	for name in jobs:
		needed = []
		for doctype, service_type in services.RECORD_SERVICE_TYPE.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			if frappe.db.exists(doctype, {"operations": name, "docstatus": ["<", 2]}):
				needed.append(service_type)
		if not needed:
			continue
		job = frappe.get_doc("Operations", name)
		have = {services.code_service_type(r.activity_code) for r in job.get("services") or [] if r.activity_code}
		added = False
		for service_type in needed:
			if service_type in have:
				continue
			code = best_code(service_type, job.mode_of_shipment, job.job_type)
			if not code:
				continue
			row = job.append("services", {"activity_code": code})
			row.db_insert()
			added = True
			field = services.SERVICE_TYPE_FIELD.get(service_type)
			if field and job.meta.has_field(field):
				job.db_set(field, 1, update_modified=False)
		if added and job.meta.has_field("service_list"):
			# The header's list of services.
			job.db_set("service_list", ", ".join(services.job_codes(job)) or None, update_modified=False)
