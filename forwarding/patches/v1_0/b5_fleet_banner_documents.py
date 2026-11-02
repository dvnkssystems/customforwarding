# Copyright (c) 2026, DVNKS Systems and contributors
"""The fleet banners name the vehicle document that expires (A-31): a
vehicle's registration (Istimara) and inspection (Fahas) now alert with its
insurance, so "Vehicle ABC-123 insurance expires ..." becomes "Vehicle
ABC-123 registration (Istimara) expires ..." when that is the one.

S5 / S9 get seed_fleet_banner_rules' new wording only while they still hold
the wording that patch first seeded, so a rule edited on a site is kept.
"""

import frappe

from forwarding.patches.v1_0 import seed_fleet_banner_rules as seed

OLD_VEHICLE = "{{ _('Vehicle {0} insurance %s {1}').format(rows[0].label, format_date(rows[0].date)) }}"
NEW_VEHICLE = (
	"{{ _('Vehicle {0} {1} %s {2}').format(rows[0].label, _(rows[0].document or 'insurance'), "
	"format_date(rows[0].date)) }}"
)


def as_seeded(template, verb):
	"""The template as first seeded, before vehicles named their document."""
	return template.replace(NEW_VEHICLE % verb, OLD_VEHICLE % verb)


def execute():
	if not frappe.db.exists("DocType", "Job Banner Rule"):
		return
	for code, template, verb in (("S5", seed.EXPIRING, "expires"), ("S9", seed.EXPIRED, "expired")):
		current = frappe.db.get_value("Job Banner Rule", code, "message_template")
		if current is not None and current == as_seeded(template, verb):
			frappe.db.set_value("Job Banner Rule", code, "message_template", template, update_modified=False)
