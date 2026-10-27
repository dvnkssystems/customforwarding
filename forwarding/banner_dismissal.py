# Copyright (c) 2026, DVNKS Systems and contributors
"""Banners a user closed with × (A-22).

Each banner carries a fingerprint of the situation it describes: the overdue
invoices it names, whether free time is on its last day, or (for any other)
its message. A dismissed banner stays hidden for that user while the
fingerprint is the same, and comes back when it changes — another invoice
falls overdue, free time reaches its last day.
"""

import hashlib

import frappe
from frappe import _

DOCTYPE = "Banner Dismissal"


def fingerprint_of(text):
	return hashlib.sha1(str(text or "").encode()).hexdigest()[:20]


def _dismissed(reference_doctype, reference_name, user=None):
	user = user or frappe.session.user
	if user == "Guest" or not frappe.db.table_exists(DOCTYPE):
		return set()
	rows = frappe.get_all(
		DOCTYPE,
		filters={"user": user, "reference_doctype": reference_doctype, "reference_name": reference_name},
		fields=["rule_code", "fingerprint"],
	)
	return {(r.rule_code, r.fingerprint or "") for r in rows}


def hide_dismissed(reference_doctype, reference_name, banners):
	"""The banners the current user has not dismissed in their present state."""
	if not banners:
		return banners
	gone = _dismissed(reference_doctype, reference_name)
	if not gone:
		return banners
	return [
		b
		for b in banners
		if ((b.get("rule_code") or b.get("code") or ""), b.get("fingerprint") or "") not in gone
	]


@frappe.whitelist(methods=["POST"])
def dismiss(reference_doctype, reference_name, rule_code, fingerprint=None):
	"""Hide one banner for the current user until its situation changes."""
	frappe.get_doc(reference_doctype, reference_name).check_permission("read")
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Log in to dismiss a banner."), frappe.PermissionError)
	filters = {"user": user, "reference_doctype": reference_doctype, "reference_name": reference_name, "rule_code": rule_code}
	name = frappe.db.get_value(DOCTYPE, filters)
	if name:
		frappe.db.set_value(DOCTYPE, name, "fingerprint", fingerprint or "")
	else:
		frappe.get_doc({"doctype": DOCTYPE, **filters, "fingerprint": fingerprint or ""}).insert(ignore_permissions=True)
	return True
