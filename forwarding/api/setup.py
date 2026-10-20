# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Setup checklist shown on the home dashboard until the basics exist.

Each step is done once a count reaches its threshold. Dismissing the whole
list, or skipping a skippable step, is remembered per user in User defaults.
"""

import json

import frappe
from frappe import _

DISMISSED_KEY = "forwarding_setup_checklist_dismissed"
SKIPPED_KEY = "forwarding_setup_checklist_skipped"

IGNORED_USERS = ("Administrator", "Guest")


def _count(doctype, filters=None):
	return frappe.db.count(doctype, filters=filters)


def _team_size():
	return _count(
		"User",
		{"enabled": 1, "user_type": "System User", "name": ["not in", IGNORED_USERS]},
	)


# key, label (translated when served), done-when, skippable, Vue route. Kept in the order the user works through them.
STEPS = (
	("customer", "Add your first customer", lambda: _count("Customer") >= 1, False, "/ui/Customer"),
	("supplier", "Add your first supplier", lambda: _count("Supplier") >= 1, False, "/ui/Supplier"),
	("charge_items", "Price your charge items", lambda: _count("Item Price") >= 1, False, "/ui/Item%20Price"),
	("vehicles", "Add your vehicles", lambda: _count("Vehicle") >= 1, True, "/ui/Vehicle"),
	("quote", "Send your first quote", lambda: _count("Quote") >= 1, False, "/quotes/new"),
	("job", "Open your first job", lambda: _count("Operations") >= 1, False, "/jobs/new"),
	("team", "Invite your team", lambda: _team_size() >= 2, False, "/ui/User"),
)
STEP_KEYS = tuple(s[0] for s in STEPS)
SKIPPABLE = {s[0] for s in STEPS if s[3]}


def _skipped():
	value = frappe.defaults.get_user_default(SKIPPED_KEY)
	try:
		skipped = json.loads(value) if value else []
	except ValueError:
		skipped = []
	return [s for s in skipped if s in SKIPPABLE]


@frappe.whitelist(methods=["GET"])
def checklist():
	"""{"dismissed": bool, "steps": [{key, label, done, skippable, skipped, route}]}.

	A skipped step also counts as done, so the frontend can hide the list
	once every step is done."""
	skipped = set(_skipped())
	steps = []
	for key, label, is_done, skippable, route in STEPS:
		steps.append(
			{
				"key": key,
				"label": _(label),
				"done": bool(is_done()) or key in skipped,
				"skippable": skippable,
				"skipped": key in skipped,
				"route": route,
			}
		)
	return {
		"dismissed": bool(frappe.utils.cint(frappe.defaults.get_user_default(DISMISSED_KEY))),
		"steps": steps,
	}


@frappe.whitelist(methods=["POST"])
def dismiss():
	frappe.defaults.set_user_default(DISMISSED_KEY, 1)
	return checklist()


@frappe.whitelist(methods=["POST"])
def skip(step):
	if step not in SKIPPABLE:
		frappe.throw(_("Step {0} cannot be skipped.").format(frappe.bold(step)))
	skipped = _skipped()
	if step not in skipped:
		skipped.append(step)
	frappe.defaults.set_user_default(SKIPPED_KEY, json.dumps(skipped))
	return checklist()
