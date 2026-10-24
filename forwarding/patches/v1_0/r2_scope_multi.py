# Copyright (c) 2026, DVNKS Systems and contributors
"""Several Scopes of Work per job, and the client's scope list (Simran, 24 Oct).

1. The scopes are renamed, created and given their Allowed Service Types
   exactly as the client listed them. A scope is found by its name or an old
   name, ignoring case; rename_doc moves every link to the new name. Where
   both a scope and an old name of it exist ("CUSTOM CLEARANCE" and "Customs
   Clearance only"), the old one is merged into it. An existing scope keeps
   its abbreviation, which is in its jobs' numbers. Scopes not in the list
   are left as they are.
2. Each job's scope_of_work becomes the first row of its Scope Of Work table.
3. The New Job wizard asks for the Scopes of Work where it asked for one.
"""

import frappe
from frappe.utils import cstr

from forwarding.api.ui_config import WIZARD_LAYOUT

FF, CC, TR = "Freight Forwarding", "Customs Clearance", "Transportation"
DOCS = "Documentation & Certification"
OTHER = ("Warehousing", "Packing & Relocation", "Value Added Services", "Cargo Insurance", "Trading")

SCOPES = (
	# name, old names, abbreviation (for a new record), allowed service types
	("Port to Port", (), "PTP", (FF,)),
	("Port to Door", (), "PTD", (FF, CC, TR)),
	("Door to Port", (), "DTP", (TR, FF, CC)),
	("Door to Door", (), "DD", (FF, CC, TR)),
	("Custom Clearance", ("Customs Clearance only",), "CC", (CC,)),
	("Destination Clearance", (), "DC", (CC,)),
	("Customs Clearance + Transportation", (), "CCT", (CC, TR)),
	("Transportation", ("Transportation only",), "TR", (TR,)),
	("SABER Services", (), "SAB", (DOCS,)),
	("Product Test Report", (), "PTR", (DOCS,)),
	("Other Services", (), "OS", OTHER),
)
OLD_FLAGS = (("freight_forwarding", FF), ("custom_clearance", CC), ("transport", TR))


def execute():
	for doctype in ("scope_of_work", "scope_of_work_service_type", "job_scope_of_work", "operations"):
		frappe.reload_doc("forwarding", "doctype", doctype)

	seed_scopes()
	backfill_job_scopes()
	update_wizard()
	frappe.cache.delete_keys("job_360")


def _existing(by_lower, name, old_names):
	"""Records standing for the scope: its own name first, then old names."""
	found = []
	for candidate in (name, *old_names):
		existing = by_lower.get(candidate.lower())
		if existing and existing not in found:
			found.append(existing)
	return found


def seed_scopes():
	for name, old_names, abbreviation, types in SCOPES:
		by_lower = {n.lower(): n for n in frappe.get_all("Scope Of Work", pluck="name")}
		found = _existing(by_lower, name, old_names)
		if not found:
			doc = frappe.new_doc("Scope Of Work").update(
				{"scope_of_work": name, "abbreviation": abbreviation}
			)
		else:
			keep, merge = found[0], found[1:]
			if keep != name:
				# Fixes case too ("PORT TO PORT"), or takes the new name.
				frappe.rename_doc("Scope Of Work", keep, name, merge=False, force=True, show_alert=False)
			for old in merge:
				frappe.rename_doc("Scope Of Work", old, name, merge=True, force=True, show_alert=False)
			doc = frappe.get_doc("Scope Of Work", name)

		doc.scope_of_work = name
		doc.set("allowed_service_types", [{"service_type": t} for t in types])
		# The old ticks follow the table, for what still reads them.
		for field, service_type in OLD_FLAGS:
			doc.set(field, 1 if service_type in types else 0)
		doc.flags.ignore_permissions = True
		doc.save() if not doc.is_new() else doc.insert()
	frappe.clear_cache(doctype="Scope Of Work")


def backfill_job_scopes():
	"""The job's one scope as the first row of its table, where it has none."""
	have = set(
		frappe.get_all(
			"Job Scope Of Work", filters={"parenttype": "Operations"}, pluck="parent", distinct=True
		)
	)
	for job in frappe.get_all(
		"Operations", filters={"scope_of_work": ["is", "set"]}, fields=["name", "scope_of_work", "docstatus"]
	):
		if job.name in have or not cstr(job.scope_of_work).strip():
			continue
		frappe.get_doc(
			{
				"doctype": "Job Scope Of Work",
				"parent": job.name,
				"parenttype": "Operations",
				"parentfield": "scopes_of_work",
				"idx": 1,
				"docstatus": job.docstatus,
				"scope_of_work": job.scope_of_work,
			}
		).db_insert()


def update_wizard():
	"""The wizard's Scope of Work row asks for the job's Scopes of Work."""
	if "custom_ui" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", WIZARD_LAYOUT):
		return
	name = frappe.db.get_value(WIZARD_LAYOUT, {"wizard": "New Job"}, "name")
	if not name:
		return
	layout = frappe.get_doc(WIZARD_LAYOUT, name)
	rows = [r for r in layout.get("fields") or [] if r.target_doctype == "Operations"]
	if any(r.fieldname == "scopes_of_work" for r in rows):
		return
	old = next((r for r in rows if r.fieldname == "scope_of_work"), None)
	if not old:
		return
	old.fieldname = "scopes_of_work"
	layout.flags.ignore_permissions = True
	layout.save()
	frappe.cache.delete_keys("ui_config:")
