# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""LCS Subscription plan-limit enforcement (Module 14).

Wired as a `validate` doc_event on the limited DocTypes. Blocks creation of new
records once the active subscription's limit for that resource is reached.
A limit of 0 means unlimited (Enterprise Plus).
"""

import frappe
from frappe import _

# doctype -> (subscription max field, subscription used field)
LIMIT_MAP = {
	"Operations": ("max_jobs", "used_jobs"),
	"Sales Invoice": ("max_invoices", "used_invoices"),
	"Purchase Invoice": ("max_invoices", "used_invoices"),
	"Freight Voucher": ("max_vouchers", "used_vouchers"),
	"Freight Tracking": ("max_awb_tracking", "used_awb_tracking"),
}


def enforce_limit(doc, method=None):
	# Only guard brand-new records; edits to existing ones are always allowed.
	if not doc.is_new():
		return
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_test:
		return

	max_field, _used = LIMIT_MAP.get(doc.doctype, (None, None))
	if not max_field:
		return

	company = getattr(doc, "company", None) or frappe.defaults.get_user_default("Company")
	sub = _active_subscription(company)
	if not sub:
		return

	limit = sub.get(max_field) or 0
	if limit <= 0:
		return  # unlimited

	current = frappe.db.count(doc.doctype)
	if current >= limit:
		frappe.throw(
			_("Subscription limit reached for {0} ({1}/{2} on plan {3}). "
			  "Please upgrade your plan.").format(doc.doctype, current, limit, sub.plan),
			title=_("Subscription Limit"),
		)


def _active_subscription(company):
	filters = {"status": "Active"}
	if company:
		filters["company"] = company
	name = frappe.db.get_value("LCS Subscription", filters)
	if not name and company:
		name = frappe.db.get_value("LCS Subscription", {"status": "Active"})
	return frappe.get_cached_doc("LCS Subscription", name) if name else None
