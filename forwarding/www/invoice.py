# Copyright (c) 2026, DVNKS Systems and contributors
"""Public invoice viewer — /invoice?token=<public_token> (no login)."""

import frappe
from frappe import _
from frappe.utils import now_datetime

no_cache = 1


def get_context(context):
	context.no_cache = 1
	token = frappe.form_dict.get("token")
	name = None
	if token:
		# A shared link expires (R3-51); one with no expiry date is from
		# before links expired and is not served either.
		name = frappe.db.get_value(
			"Sales Invoice",
			{
				"public_token": token,
				"is_public": 1,
				"docstatus": 1,
				"public_link_expires_on": [">", now_datetime()],
			},
			"name",
		)
	if not name:
		context.invoice = None
		context.error = _("Invoice not found, not shared publicly, or the link has expired.")
		return context

	doc = frappe.get_doc("Sales Invoice", name)
	context.invoice = doc
	try:
		context.print_html = frappe.get_print("Sales Invoice", name)
	except Exception:
		context.print_html = None
	return context
