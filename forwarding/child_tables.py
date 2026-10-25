# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Rules for the child tables a job shares with its Transportation and Custom
Clearance records: Document Table, Cost Table and Activity Template Table.

Wired up in hooks.py as a validate doc_event on Operations, Transportation
and Custom Clearance, so the three behave the same whichever form (desk or
the Vue app) saved them.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, nowdate

ACTIVITY_DONE = "Done"


def apply(doc, method=None):
	if doc.docstatus == 2:
		return
	validate_document_rows(doc)
	set_document_received(doc)
	set_cost_amounts(doc)
	set_cost_suppliers(doc)
	set_activity_dates(doc)


def validate_document_rows(doc, method=None):
	"""A document row names its document (R3-06).

	"+ Add document" left rows with nothing chosen, which saved as
	"Document 1 - Awaiting" and stayed on the job. Refuse them on the
	Documents table (Document) and on the clearance documents table
	(Document Type), naming the rows, so the user picks one or removes it.
	Runs on validate and, for a submitted job, before_update_after_submit."""
	if doc.docstatus == 2:
		return
	problems = []
	for fieldname, column in (("document_table", "document"), ("clearance_documents", "document_type")):
		if not doc.meta.has_field(fieldname):
			continue
		blank = [row.idx for row in doc.get(fieldname) or [] if not cstr(row.get(column)).strip()]
		if blank:
			label = _(doc.meta.get_label(fieldname))
			what = _(frappe.get_meta(doc.meta.get_field(fieldname).options).get_label(column))
			rows = ", ".join(str(i) for i in blank)
			if len(blank) == 1:
				message = _("{0}: row {1} has no {2}. Choose one or remove the row.")
			else:
				message = _("{0}: rows {1} have no {2}. Choose one or remove the rows.")
			problems.append(message.format(label, rows, what))
	if problems:
		frappe.throw("<br>".join(problems), title=_("Document missing"))


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


def undate_unreceived_documents(doc):
	"""Clear the date of every document row not marked received."""
	for row in doc.get("document_table") or []:
		if cstr(row.received).strip() != "Yes":
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


# The supplier a new cost row is bought from by default, per parent DocType:
# the first of these fields that is set. A job's own rows have no default.
COST_SUPPLIER_FIELDS = {
	"Transportation": ("transporter",),
	"Custom Clearance": ("transporter_name", "broker_name"),
}


def default_cost_supplier(doc):
	for field in COST_SUPPLIER_FIELDS.get(doc.doctype, ()):
		if doc.get(field):
			return doc.get(field)
	return None


def set_cost_suppliers(doc):
	"""Give each new cost row with no supplier the record's transporter (or,
	on a Custom Clearance with none, its broker).

	Only rows added in this save: a row that already existed keeps whatever
	the user left in it, blank included."""
	supplier = default_cost_supplier(doc)
	if not supplier:
		return
	before = doc.get_doc_before_save() if not doc.is_new() else None
	existing = {r.name for r in (before.get("cost_table") or [])} if before else set()
	for row in doc.get("cost_table") or []:
		if not row.supplier and (not row.name or row.name not in existing):
			row.supplier = supplier


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


def job_containers(job):
	"""(container number, "size type") of each numbered row in the job's
	Container tab, in order."""
	containers = []
	for row in job.get("container_details") or []:
		number = cstr(row.container_no).strip()
		if number:
			size = f"{row.size}'" if row.size else ""
			containers.append((number, " ".join(part for part in (size, cstr(row.container_type)) if part)))
	return containers


def add_clearance_containers(clearance, containers):
	"""Append to a Custom Clearance's Containers table each container it does
	not list yet, as Pending. Returns the rows appended (not saved)."""
	have = {cstr(r.container_no).strip().upper() for r in clearance.get("clearance_containers") or []}
	added = []
	for number, size_type in containers:
		if number.upper() in have:
			continue
		added.append(
			clearance.append(
				"clearance_containers",
				{"container_no": number, "container_type": size_type, "clearance_status": "Pending"},
			)
		)
		have.add(number.upper())
	return added


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
	# The controller's validate runs before the apply() doc_event: default
	# the rows' supplier first, so the job's copies carry it.
	set_cost_suppliers(doc)
	if not doc.get("operations") or not doc.get("cost_table"):
		return

	job_rows = {
		r.name: r
		for r in frappe.get_all(
			"Cost Table",
			filters={"parent": doc.operations, "parenttype": "Operations", "parentfield": "cost_table"},
			fields=["name", "item", "account", "cost", "supplier", "idx"],
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
			values = {
				"item": row.item,
				"account": row.account,
				"supplier": row.get("supplier"),
				"cost": flt(row.cost),
				"amount": flt(row.cost),
			}
			if any(
				cstr(copy.get(k) or "") != cstr(v or "") for k, v in values.items() if k in ("item", "account", "supplier")
			) or flt(copy.cost) != flt(row.cost):
				frappe.db.set_value("Cost Table", copy.name, values, update_modified=False)
			continue

		same_item = next((r for r in job_rows.values() if r.item == row.item and r.name not in claimed), None)
		if same_item:
			row.ref_id = same_item.name
			claimed.add(same_item.name)
			if row.get("supplier") and not same_item.get("supplier"):
				frappe.db.set_value("Cost Table", same_item.name, "supplier", row.supplier, update_modified=False)
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
				"supplier": row.get("supplier"),
				"account": row.account,
				"cost": flt(row.cost),
				"amount": flt(row.cost),
				"ref_docname": doc.name,
			}
		)
		new.db_insert()
		next_idx += 1
		job_rows[new.name] = frappe._dict(
			name=new.name, item=row.item, account=row.account, cost=flt(row.cost), supplier=row.get("supplier"), idx=new.idx
		)
		row.ref_id = new.name
		claimed.add(new.name)
