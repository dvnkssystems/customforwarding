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
	"""Attaching a file means the document is in hand: mark it received.

	A row's date is the day it was received: today when it becomes received
	without one, and none while it is not received (rows copied from the job
	or a Shipment Type used to arrive dated)."""
	for row in doc.get("document_table") or []:
		if row.attach and cstr(row.received).strip() != "Yes":
			row.received = "Yes"
		if cstr(row.received).strip() == "Yes":
			if not row.date:
				row.date = nowdate()
		elif row.date:
			row.date = None


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
		if fieldname == "document_table" and cstr(row.received).strip() != "Yes":
			row.date = None
		row.db_insert()
		copied += 1
	return copied


def is_customs_document(row):
	return cstr(row.stage).strip() == "Customs Clearance"


def sync_costs_to_job(doc):
	"""Keep a copy of each of a Transportation / Custom Clearance's cost rows
	on its job, so the job's Cost Table carries every charge.

	The origin row's ref_id names the job's copy. A row without one takes the
	job's row for the same item if there is one (as before), or gets a new row
	appended to the job; the copy's ref_docname names the origin record. A
	row with one updates its copy when the item, account or cost changed.

	Replaces the per-DocType code that set ref_id with db.set_value on a row
	not inserted yet (so it never stuck and the charge was counted twice) and
	called an update method that did not exist (so a third save raised).
	"""
	if not doc.get("operations") or not doc.get("cost_table"):
		return

	job_rows = {
		r.name: r
		for r in frappe.get_all(
			"Cost Table",
			filters={"parent": doc.operations, "parenttype": "Operations", "parentfield": "cost_table"},
			fields=["name", "item", "account", "cost", "idx"],
		)
	}
	next_idx = max((r.idx for r in job_rows.values()), default=0) + 1
	# Job rows already standing for another record's cost row.
	claimed = set(
		frappe.get_all(
			"Cost Table",
			filters={"ref_id": ["in", list(job_rows) or [""]], "parent": ["!=", doc.name]},
			pluck="ref_id",
		)
	)

	for row in doc.cost_table:
		if not row.item:
			continue
		copy = job_rows.get(row.ref_id) if row.ref_id else None
		if copy:
			values = {"item": row.item, "account": row.account, "cost": flt(row.cost), "amount": flt(row.cost)}
			if any(cstr(copy.get(k) or "") != cstr(v or "") for k, v in values.items() if k in ("item", "account")) or flt(
				copy.cost
			) != flt(row.cost):
				frappe.db.set_value("Cost Table", copy.name, values, update_modified=False)
			continue

		same_item = next((r for r in job_rows.values() if r.item == row.item and r.name not in claimed), None)
		if same_item:
			row.ref_id = same_item.name
			claimed.add(same_item.name)
			continue

		new = frappe.get_doc(
			{
				"doctype": "Cost Table",
				"parent": doc.operations,
				"parenttype": "Operations",
				"parentfield": "cost_table",
				"idx": next_idx,
				"item": row.item,
				"item_name": row.item_name,
				"account": row.account,
				"cost": flt(row.cost),
				"amount": flt(row.cost),
				"ref_docname": doc.name,
			}
		)
		new.db_insert()
		next_idx += 1
		job_rows[new.name] = frappe._dict(name=new.name, item=row.item, account=row.account, cost=flt(row.cost), idx=new.idx)
		row.ref_id = new.name
		claimed.add(new.name)
