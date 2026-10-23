# Copyright (c) 2026, Forwarding and contributors
# For license information, please see license.txt
"""
Estimation vs Actual, per job.

What operations expected a job to earn and spend, beside what the ledger
actually recorded against it.

Converted from a Query Report. That version could not run at all — it selected
`tabOperations`.operation_status, and the column is `operations_status`, so the
report failed with "Unknown column 'operation_status'". Three further problems
came with it, each fixed here and each changing the numbers:

1.  **Estimates came from `total_rate` / `total_cost`.** Those columns still
    exist on `tabOperations` but are no longer DocFields and nothing in this app
    writes them — they are orphans from an older schema, and they have already
    drifted from the cost sheet (by ~300 on income and ~1,400 on expense across
    the table). The estimate is taken from the `Cost Table` child instead, which
    is what the form actually edits.

2.  **Credits and debits were not netted.** Every credit counted as income and
    every debit as expense, across both account types. A credit note against an
    income account therefore *increased* reported expense. Income is now
    credit − debit on income accounts, expense debit − credit on cost accounts.

3.  **No company, no date, no filters at all.** The report returned every job
    ever, from every company. Filters are below.

Cancelled jobs are left out unless Include Cancelled Jobs is ticked, and then
read as Cancelled (M-19). Var % shows only when the estimated profit is above
zero (M-20).

`is_cancelled` was also being tested inside the `tabAccount` sub-query rather
than against the ledger rows; it is a plain condition on the join here.
"""

import frappe
from frappe import _

# The figures themselves live in forwarding.estimation, shared with the
# Charges tab on Job 360 so the two always agree (M-03).
from forwarding.estimation import figures


def execute(filters=None):
	data = figures(filters)
	if not data:
		return get_columns(), [], ""
	return get_columns(), data, get_message(data)


def get_message(data):
	"""The one caveat that changes how the table should be read.

	A job with cost booked and nothing billed is not a loss-making job; it is an
	unbilled one. Saying so above the table costs nothing and stops the red
	numbers being taken at face value.
	"""
	unbilled = [row for row in data if not row["billed"] and row["actual_expense"]]
	untagged = [row for row in data if not row["actual_income"] and not row["actual_expense"]]

	parts = []
	if unbilled:
		cost = sum(row["actual_expense"] for row in unbilled)
		parts.append(
			_("{0} have cost booked and nothing billed yet ({1} of expense) — a negative Actual Profit there is an unbilled job, not a loss.")
			.format(len(unbilled), frappe.format_value(cost, {"fieldtype": "Currency"}))
		)
	if untagged:
		parts.append(
			_("{0} have no ledger entry tagged to them at all, which reads the same as earning nothing — check the Project field on the invoice.")
			.format(len(untagged))
		)
	if not parts:
		return ""

	return _("Of {0} jobs: ").format(len(data)) + " ".join(parts)


def get_columns():
	return [
		{"label": _("Job"), "fieldname": "operation", "fieldtype": "Link", "options": "Operations", "width": 190},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 200},
		{"label": _("Branch"), "fieldname": "branch", "fieldtype": "Link", "options": "Branch", "width": 110},
		{"label": _("Mode"), "fieldname": "mode_of_shipment", "fieldtype": "Data", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Est. Income"), "fieldname": "estimated_income", "fieldtype": "Currency", "width": 120},
		{"label": _("Est. Expense"), "fieldname": "estimated_expense", "fieldtype": "Currency", "width": 120},
		{"label": _("Est. Profit"), "fieldname": "estimated_profit", "fieldtype": "Currency", "width": 120},
		{"label": _("Actual Income"), "fieldname": "actual_income", "fieldtype": "Currency", "width": 125},
		{"label": _("Actual Expense"), "fieldname": "actual_expense", "fieldtype": "Currency", "width": 130},
		{"label": _("Actual Profit"), "fieldname": "actual_profit", "fieldtype": "Currency", "width": 125},
		{"label": _("Variance"), "fieldname": "variance", "fieldtype": "Currency", "width": 120},
		{"label": _("Var %"), "fieldname": "variance_pct", "fieldtype": "Percent", "width": 80},
		{"label": _("Billed"), "fieldname": "billed", "fieldtype": "Check", "width": 60},
		{"label": _("Last Posting"), "fieldname": "last_posting", "fieldtype": "Date", "width": 110},
		{"label": _("Late"), "fieldname": "late_posting", "fieldtype": "Check", "width": 60},
	]
