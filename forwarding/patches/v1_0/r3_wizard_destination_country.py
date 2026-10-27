# Copyright (c) 2026, DVNKS Systems and contributors
"""Show Destination Country on the New Job wizard's Route step (R3-05).

It follows Port of Discharge (fetched from the port; Saudi Arabia on an
import). A "New Job" Custom UI Wizard Layout seeded before then lists the
Route step without it, so it is inserted right after Port of Discharge — or
at the end of the step when the layout has no such row. A layout that already
has the field, in any step, is left as the admin set it.
"""

import frappe

from forwarding.api.ui_config import CACHE_PREFIX, WIZARD_LAYOUT, WIZARDS

WIZARD = "New Job"
STEP = "route"
FIELD = "destination_country"
AFTER = "port_of_destination"


def execute():
	if "custom_ui" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", WIZARD_LAYOUT):
		return
	name = frappe.db.get_value(WIZARD_LAYOUT, {"wizard": WIZARD}, "name")
	if not name:
		return  # seed_ui_config creates it with every default field

	target = WIZARDS[WIZARD]["target_doctype"]
	if not frappe.get_meta(target).get_field(FIELD):
		return

	layout = frappe.get_doc(WIZARD_LAYOUT, name)
	rows = list(layout.get("fields") or [])
	if any(r.fieldname == FIELD and r.target_doctype == target for r in rows):
		return

	anchor = next((i for i, r in enumerate(rows) if r.fieldname == AFTER and r.section == STEP), None)
	if anchor is None:
		in_step = [i for i, r in enumerate(rows) if r.section == STEP]
		anchor = in_step[-1] if in_step else len(rows) - 1

	row = layout.append("fields", {"section": STEP, "target_doctype": target, "fieldname": FIELD})
	rows.insert(anchor + 1, row)
	for idx, r in enumerate(rows, start=1):
		r.idx = idx
	layout.set("fields", rows)
	layout.flags.ignore_permissions = True
	layout.save()
	frappe.cache.delete_keys(CACHE_PREFIX)
