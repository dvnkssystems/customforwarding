# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Bulk actions on the app's lists (A-40): what the user may do to a
DocType's records, and doing one of those to the ticked rows.

Frappe has bulk endpoints (bulk_update.submit_cancel_or_update_docs,
reportview.delete_items), but they answer only with the names that failed,
not why, and hand anything past 20 (10 for delete) to a background job that
reports nothing back. The list has to say "3 submitted, 1 failed: <reason>",
so run() calls the same document methods (submit, cancel, save,
frappe.delete_doc, each with its own permission check) row by row and keeps
each row's outcome. Export is a CSV built in the app from the list's rows,
and Print uses Frappe's download_multi_pdf, so neither needs a method here.
"""

import re

import frappe
from frappe import _
from frappe.utils import strip_html

ACTIONS = ("submit", "cancel", "delete", "set")
# The same ceiling as a page of rows many times over, and short enough to run
# inside one request.
MAX_ROWS = 100
PERMS = ("read", "write", "create", "delete", "submit", "cancel", "export", "print")
# Fields a value can be typed into from the list; tables, attachments and
# text editors need the form.
SETTABLE = {"Data", "Select", "Link", "Check", "Date", "Datetime", "Int", "Float", "Currency", "Percent", "Small Text"}


@frappe.whitelist()
def permissions(doctype):
	"""{perms: {read, write, ...}, is_submittable, fields: [...]} for the
	session user; fields are those Set field may change."""
	frappe.has_permission(doctype, "read", throw=True)
	meta = frappe.get_meta(doctype)
	perms = {ptype: bool(frappe.has_permission(doctype, ptype)) for ptype in PERMS}
	if not meta.is_submittable:
		perms["submit"] = perms["cancel"] = False
	return {
		"perms": perms,
		"is_submittable": bool(meta.is_submittable),
		"fields": settable_fields(meta) if perms["write"] else [],
	}


def settable_fields(meta):
	return [
		{
			"fieldname": f.fieldname,
			"label": _(f.label) if f.label else f.fieldname,
			"fieldtype": f.fieldtype,
			"options": f.options if f.fieldtype in ("Select", "Link") else None,
		}
		for f in meta.fields
		if f.fieldtype in SETTABLE
		and not (f.hidden or f.read_only or f.permlevel or f.fetch_from or f.is_virtual or f.set_only_once)
	]


@frappe.whitelist(methods=["POST"])
def run(doctype, names, action, fieldname=None, value=None):
	"""Apply `action` to each of `names`; {done, failed: [{name, error}]}.

	Each row runs in its own savepoint, so one that fails rolls back alone
	and the others stand."""
	names = frappe.parse_json(names) if isinstance(names, str) else names
	if action not in ACTIONS:
		frappe.throw(_("Unknown bulk action {0}").format(action))
	if not isinstance(names, list) or not names:
		frappe.throw(_("Tick at least one row"))
	names = list(dict.fromkeys(str(n) for n in names))
	if len(names) > MAX_ROWS:
		frappe.throw(_("Bulk actions take up to {0} rows at a time").format(MAX_ROWS))
	meta = frappe.get_meta(doctype)
	if action in ("submit", "cancel") and not meta.is_submittable:
		frappe.throw(_("{0} records are not submitted").format(_(doctype)))
	if action == "set":
		field = next((f for f in settable_fields(meta) if f["fieldname"] == fieldname), None)
		if not field:
			frappe.throw(_("{0} cannot be set from the list").format(fieldname or _("This field")))

	done, failed = [], []
	for name in names:
		savepoint = "bulk_" + re.sub(r"\W", "_", frappe.generate_hash(length=8))
		frappe.db.savepoint(savepoint)
		try:
			apply(doctype, name, action, fieldname, value)
			done.append(name)
		except Exception as e:
			error = reason(e)
			try:
				frappe.db.rollback(save_point=savepoint)
			except Exception:
				# Something on the way committed, which ends the savepoint;
				# what it committed stands, as it would from the form.
				pass
			failed.append({"name": name, "error": error})
		finally:
			# A row's own msgprints (and those of a failed one) are not the
			# summary the list shows.
			frappe.local.message_log = []
	return {"done": done, "failed": failed}


def apply(doctype, name, action, fieldname, value):
	if action == "delete":
		frappe.delete_doc(doctype, name)
		return
	doc = frappe.get_doc(doctype, name)
	if action == "submit":
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft can be submitted"))
		doc.submit()
	elif action == "cancel":
		if doc.docstatus != 1:
			frappe.throw(_("Only a submitted record can be cancelled"))
		doc.cancel()
	else:
		if doc.docstatus == 2:
			frappe.throw(_("A cancelled record cannot be changed"))
		doc.set(fieldname, value)
		doc.save()


def reason(e):
	"""The message the user would have seen, as one plain line."""
	logged = [frappe.parse_json(m).get("message") for m in frappe.local.message_log or []]
	text = next((m for m in reversed(logged) if m), None) or str(e) or e.__class__.__name__
	return re.sub(r"\s+", " ", strip_html(str(text))).strip()[:300]
