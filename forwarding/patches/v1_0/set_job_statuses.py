# Copyright (c) 2026, DVNKS Systems and contributors
"""Move jobs onto the new status list.

The statuses are Draft, Open, On Hold, Delivered, Ops Completed, Closed and
Cancelled. Older sites carry OPEN and Completed, which map to Open and Ops
Completed; Closed keeps its name.

OPEN -> Open differs only in case. MariaDB compares names without case, so
rename_doc would see "Open" as already taken. The rows are rewritten in SQL
instead, matching the old value byte for byte, which also makes the patch
safe to run twice.
"""

import frappe
from frappe.model.rename_doc import get_link_fields

STATUSES = ("Draft", "Open", "On Hold", "Delivered", "Ops Completed", "Closed", "Cancelled")
RENAMES = {"OPEN": "Open", "Completed": "Ops Completed"}


def execute():
	for old, new in RENAMES.items():
		remap(old, new)

	for status in STATUSES:
		if not frappe.db.exists("Operations Status", status):
			frappe.get_doc({"doctype": "Operations Status", "status": status}).insert(ignore_permissions=True)

	frappe.clear_cache(doctype="Operations Status")


def remap(old, new):
	"""Point every reference to `old` at `new`, then retire or rename `old`."""
	have_old = frappe.db.sql("select name from `tabOperations Status` where binary name = %s", old)
	if not have_old:
		return

	have_new = frappe.db.sql("select name from `tabOperations Status` where binary name = %s", new)
	if have_new:
		frappe.db.sql("delete from `tabOperations Status` where binary name = %s", old)
	else:
		frappe.db.sql(
			"update `tabOperations Status` set name = %s, status = %s where binary name = %s",
			(new, new, old),
		)

	# Table and column names come from the DocType metadata, not user input;
	# identifiers cannot be bound as parameters, the values are.
	for link in get_link_fields("Operations Status"):
		if link.get("issingle"):
			continue
		frappe.db.sql(
			"update `tab{0}` set `{1}` = %s where binary `{1}` = %s".format(
				link["parent"], link["fieldname"]
			),
			(new, old),
		)
