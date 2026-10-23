# Copyright (c) 2026, DVNKS Systems and contributors
"""Several services per job, decided by its Scope of Work (M-05, M-06, M-21, R2-23).

1. Freight Activity Codes get a Job Type, read from their names ("Sea Export
   Clearance" is for Export jobs; "Land Local Freight" suits any), and the
   service types the client was missing get a code each (M-21).
2. The seven scopes from the client's table get their Allowed Service Types.
   An existing scope whose name matches, ignoring case, is reused; its rows
   are set only when it has none. Other scopes with no rows get them from
   their old Freight Forwarding / Custom Clearance / Transport ticks; one with
   none of those stays empty, which allows every service.
3. Every job with an Activity Code gets it as its first Service.
4. The New Job wizard asks for Scope of Work, then Services, where it asked
   for Activity Code.
"""

import frappe

from forwarding.api.ui_config import WIZARD_LAYOUT

NEW_CODES = (
	# name, mode, service type
	("Warehousing", "Other", "Warehousing"),
	("Packing & Relocation", "Other", "Packing & Relocation"),
	("Cargo Insurance", "Other", "Cargo Insurance"),
	("SABER Certification", "Other", "Documentation & Certification"),
	("Certificate of Origin", "Other", "Documentation & Certification"),
)

FF, CC, TR = "Freight Forwarding", "Customs Clearance", "Transportation"
SCOPES = (
	# name, abbreviation (for a new record), allowed service types
	("Port to Port", "PTP", (FF,)),
	("Port to Door", "PTD", (FF, CC, TR)),
	("Door to Port", "DTP", (TR, FF, CC)),
	("Door to Door", "DD", (FF, CC, TR)),
	("Customs Clearance only", "CCO", (CC,)),
	("Customs Clearance + Transportation", "CCT", (CC, TR)),
	("Transportation only", "TRO", (TR,)),
)
OLD_FLAGS = (("freight_forwarding", FF), ("custom_clearance", CC), ("transport", TR))


def execute():
	for doctype in ("freight_activity_code", "operations_service", "scope_of_work_service_type", "scope_of_work", "operations"):
		frappe.reload_doc("forwarding", "doctype", doctype)

	set_code_job_types()
	add_codes()
	seed_scopes()
	backfill_job_services()
	update_wizard()
	frappe.cache.delete_keys("job_360")


def code_job_type(name):
	for job_type in ("Export", "Import"):
		if job_type.lower() in name.lower() and frappe.db.exists("Job Type", job_type):
			return job_type
	return None


def set_code_job_types():
	for code in frappe.get_all("Freight Activity Code", filters={"job_type": ["is", "not set"]}, pluck="name"):
		job_type = code_job_type(code)
		if job_type:
			frappe.db.set_value("Freight Activity Code", code, "job_type", job_type, update_modified=False)


def add_codes():
	for name, mode, service_type in NEW_CODES:
		if frappe.db.exists("Freight Activity Code", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Freight Activity Code",
				"activity_name": name,
				"mode": mode,
				"service_type": service_type,
			}
		).insert(ignore_permissions=True)


def seed_scopes():
	by_lower = {n.lower(): n for n in frappe.get_all("Scope Of Work", pluck="name")}
	seeded = set()
	for name, abbreviation, types in SCOPES:
		existing = by_lower.get(name.lower())
		doc = (
			frappe.get_doc("Scope Of Work", existing)
			if existing
			else frappe.new_doc("Scope Of Work").update({"scope_of_work": name, "abbreviation": abbreviation})
		)
		seeded.add(doc.name or name)
		if doc.get("allowed_service_types"):
			continue
		for service_type in types:
			doc.append("allowed_service_types", {"service_type": service_type})
		# The old ticks follow the table, for what still reads them.
		for field, service_type in OLD_FLAGS:
			doc.set(field, 1 if service_type in types else 0)
		doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)

	for name in frappe.get_all("Scope Of Work", pluck="name"):
		if name in seeded:
			continue
		doc = frappe.get_doc("Scope Of Work", name)
		if doc.get("allowed_service_types"):
			continue
		types = [service_type for field, service_type in OLD_FLAGS if doc.get(field)]
		if not types:
			continue
		for service_type in types:
			doc.append("allowed_service_types", {"service_type": service_type})
		doc.save(ignore_permissions=True)


def backfill_job_services():
	have = set(frappe.get_all("Operations Service", filters={"parenttype": "Operations"}, pluck="parent", distinct=True))
	jobs = frappe.get_all(
		"Operations",
		filters={"activity_code": ["is", "set"]},
		fields=["name", "activity_code", "docstatus"],
	)
	for job in jobs:
		if job.name in have:
			continue
		code = frappe.db.get_value(
			"Freight Activity Code", job.activity_code, ["service_type", "mode"], as_dict=True
		) or {}
		row = frappe.get_doc(
			{
				"doctype": "Operations Service",
				"parent": job.name,
				"parenttype": "Operations",
				"parentfield": "services",
				"idx": 1,
				"docstatus": job.docstatus,
				"activity_code": job.activity_code,
				"service_type": code.get("service_type"),
				"mode": code.get("mode"),
			}
		)
		row.db_insert()
		frappe.db.set_value("Operations", job.name, "service_list", job.activity_code, update_modified=False)


def update_wizard():
	"""Activity Code's row becomes Scope of Work then Services, in its step."""
	if "custom_ui" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", WIZARD_LAYOUT):
		return
	name = frappe.db.get_value(WIZARD_LAYOUT, {"wizard": "New Job"}, "name")
	if not name:
		return
	layout = frappe.get_doc(WIZARD_LAYOUT, name)
	rows = [r for r in layout.get("fields") or [] if r.target_doctype == "Operations"]
	have = {r.fieldname for r in rows}
	old = next((r for r in rows if r.fieldname == "activity_code"), None)
	if not old or "services" in have:
		return

	section = old.section
	old.fieldname, old.label = "services", "Services"
	if "scope_of_work" not in have:
		# Insert before Services: rebuild the order with the new row in place.
		fields = list(layout.fields)
		position = fields.index(old)
		new = layout.append(
			"fields", {"section": section, "target_doctype": "Operations", "fieldname": "scope_of_work"}
		)
		fields.insert(position, new)
		layout.fields = fields
		for idx, row in enumerate(layout.fields, start=1):
			row.idx = idx
	layout.flags.ignore_permissions = True
	layout.save()
	frappe.cache.delete_keys("ui_config:")
