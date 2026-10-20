# Copyright (c) 2026, DVNKS Systems and contributors
"""Activity Template Table status is now a Select of Pending / In Progress /
Done. Map the free text typed before: finished-sounding words to Done,
started-sounding ones to In Progress, any other text to Pending. Blank stays
blank."""

import frappe
from frappe.utils import cstr

DONE = {"done", "complete", "completed", "finished", "finish", "closed", "yes", "ok"}
IN_PROGRESS = {"in progress", "in-progress", "inprogress", "progress", "working", "started", "ongoing", "wip"}


def map_status(value):
	text = cstr(value).strip()
	key = text.lower()
	if not key:
		return None
	if key in DONE:
		return "Done"
	if key in IN_PROGRESS:
		return "In Progress"
	return "Pending"


def execute():
	frappe.reload_doc("forwarding", "doctype", "activity_template_table")
	table = frappe.qb.DocType("Activity Template Table")
	rows = frappe.qb.from_(table).select(table.name, table.status).where(table.status.isnotnull()).run(as_dict=True)
	for row in rows:
		mapped = map_status(row.status)
		if mapped != row.status:
			frappe.qb.update(table).set(table.status, mapped).where(table.name == row.name).run()
