# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Rules for the child tables a job shares with its Transportation and Custom
Clearance records: Document Table, Cost Table and Activity Template Table.

Wired up in hooks.py as a validate doc_event on Operations, Transportation
and Custom Clearance, so the three behave the same whichever form (desk or
the Vue app) saved them.
"""

import frappe
from frappe.utils import cstr, flt, nowdate

ACTIVITY_DONE = "Done"


def apply(doc, method=None):
	if doc.docstatus == 2:
		return
	set_document_received(doc)
	set_cost_amounts(doc)
	set_activity_dates(doc)


def set_document_received(doc):
	"""Attaching a file means the document is in hand: mark it received and
	date it today unless a date was already entered."""
	for row in doc.get("document_table") or []:
		if row.attach and cstr(row.received).strip() != "Yes":
			row.received = "Yes"
			if not row.date:
				row.date = nowdate()


def set_cost_amounts(doc):
	"""amount is the row's buying amount, which is Cost alone (not Cost x Rate:
	Rate is the selling amount of the same charge). Rows without an account
	take the item's default expense account for the company."""
	company = doc.get("company") or frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
	for row in doc.get("cost_table") or []:
		row.amount = flt(row.cost)
		if row.item and not row.account and company:
			row.account = _default_expense_account(row.item, company)


def _default_expense_account(item, company):
	from erpnext.stock.doctype.item.item import get_item_defaults

	return get_item_defaults(item, company).get("expense_account") or None


def set_activity_dates(doc):
	"""An activity marked Done is dated today unless it already has a date."""
	for row in doc.get("activity_template_table") or []:
		if row.status == ACTIVITY_DONE and not row.date:
			row.date = nowdate()


def copy_from_job(doc, fieldname, condition=None):
	"""Copy the job's rows of one table onto a newly inserted linked record.

	Only when the record arrived with none: the Create menu builds it with the
	make_* mappers in operations.py, which already copy the rows, and copying
	again would double them. Rows are written directly so the record is not
	saved (and validated) a second time from inside its own insert.
	"""
	if not doc.get("operations") or doc.get(fieldname):
		return 0

	job = frappe.get_doc("Operations", doc.operations)
	copied = 0
	for source in job.get(fieldname) or []:
		if condition and not condition(source):
			continue
		row = doc.append(fieldname, source.as_dict(no_default_fields=True))
		row.db_insert()
		copied += 1
	return copied


def is_customs_document(row):
	return cstr(row.stage).strip() == "Customs Clearance"
