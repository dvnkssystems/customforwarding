# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 2: Default Salesperson on the Customer (M-04) and document rows
that must name a document (R2-14).

* Customer.default_salesperson is new. Each customer without one takes the
  salesperson its Customer 360 page already showed: the first Sales Team
  row, else the free-text Sales Person1, else the salesman on its latest
  job -- only when that is a real Sales Person record.
* Document Table.document is now mandatory. A row with nothing in it (no
  document, file, remark, and not received) is dropped, so the job it sits
  on can still be saved. A row that holds anything else is kept for someone
  to name.

Running it again changes nothing.
"""

import json
import os

import frappe

from forwarding.api.customer_360 import _salesman


def execute():
	backfill_default_salesperson()
	drop_empty_document_rows()


def _sync_customer_customizations():
	"""Migrate syncs the app's custom/*.json after the post-model-sync
	patches; default_salesperson comes from custom/customer.json, so sync
	that one file first."""
	from frappe.modules.utils import sync_customizations_for_doctype

	path = frappe.get_app_path("forwarding", "forwarding", "custom", "customer.json")
	with open(path) as f:
		data = json.load(f)
	sync_customizations_for_doctype(data, os.path.dirname(path), "customer.json")


def backfill_default_salesperson():
	_sync_customer_customizations()
	for name in frappe.get_all("Customer", filters={"default_salesperson": ["is", "not set"]}, pluck="name"):
		salesman = _salesman(frappe.get_doc("Customer", name))
		if salesman and frappe.db.exists("Sales Person", salesman):
			frappe.db.set_value("Customer", name, "default_salesperson", salesman, update_modified=False)


def drop_empty_document_rows():
	table = frappe.qb.DocType("Document Table")
	blank = lambda column: column.isnull() | (column == "")  # noqa: E731
	(
		frappe.qb.from_(table)
		.delete()
		.where(blank(table.document))
		.where(blank(table.attach))
		.where(blank(table.remark))
		.where(table.received.isnull() | (table.received != "Yes"))
	).run()
