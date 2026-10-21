# Copyright (c) 2026, DVNKS Systems and contributors
"""Give the New Job wizard's Cargo step its weight and volume fields (C28).

The built-in defaults (forwarding.api.ui_config.WIZARDS) list packages,
net / gross weight, weight UOM, CBM and cargo description, but a "New Job"
Custom UI Wizard Layout seeded or edited before then may carry only
Commodity. Each missing field is appended to the cargo section. A field the
layout already has, in any section and whatever its settings, is left as
the admin set it, and no row is removed.
"""

import frappe

from forwarding.api.ui_config import WIZARD_LAYOUT, WIZARDS

WIZARD = "New Job"
STEP = "cargo"


def execute():
	if "custom_ui" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", WIZARD_LAYOUT):
		return
	name = frappe.db.get_value(WIZARD_LAYOUT, {"wizard": WIZARD}, "name")
	if not name:
		return  # seed_ui_config creates it with every default field

	spec = WIZARDS[WIZARD]
	target = spec["target_doctype"]
	meta = frappe.get_meta(target)
	wanted = next(s["fields"] for s in spec["steps"] if s["key"] == STEP)

	layout = frappe.get_doc(WIZARD_LAYOUT, name)
	have = {r.fieldname for r in layout.get("fields") or [] if r.target_doctype == target}
	missing = [f for f in wanted if f not in have and meta.get_field(f)]
	if not missing:
		return

	for fieldname in missing:
		layout.append(
			"fields",
			{"section": STEP, "target_doctype": target, "fieldname": fieldname, "label": spec["labels"].get(fieldname)},
		)
	layout.flags.ignore_permissions = True
	layout.save()
	frappe.cache.delete_keys("ui_config:")
