# Copyright (c) 2026, DVNKS Systems and contributors
"""Fill the Account on estimate rows that have an Item and none (B3-13).

A job made from a quote opened with blank accounts and kept them until it was
saved again. Each such row on a job that is not cancelled takes the account
its next save would give it (default_expense_account: the item's, its
group's, or the company's default expense account). Rows with no Item are
left for whoever prices the job. Rows are written directly; the jobs are not
saved.
"""

import frappe

from forwarding.forwarding.doctype.operations.operations import default_expense_account


def execute():
	rows = frappe.db.sql(
		"""
		SELECT ct.name, ct.item, ops.company
		FROM `tabCost Table` ct
		INNER JOIN `tabOperations` ops ON ops.name = ct.parent
		WHERE ct.parenttype = 'Operations'
		  AND IFNULL(ct.account, '') = ''
		  AND IFNULL(ct.item, '') != ''
		  AND ops.docstatus < 2
		  AND IFNULL(ops.operations_status, '') != 'Cancelled'
		""",
		as_dict=True,
	)
	for row in rows:
		account = default_expense_account(row.item, row.company)
		if account:
			frappe.db.set_value("Cost Table", row.name, "account", account, update_modified=False)
