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

`is_cancelled` was also being tested inside the `tabAccount` sub-query rather
than against the ledger rows; it is a plain condition on the join here.
"""

import frappe
from frappe import _
from frappe.utils import flt

# The account types that make up a job's revenue and its cost of sale. Kept
# exactly as the original report had them so the figures stay comparable —
# widening this to include every Expense Account would change every row.
INCOME_ACCOUNT_TYPES = ("Income Account",)
EXPENSE_ACCOUNT_TYPES = ("Cost of Goods Sold",)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	jobs = get_jobs(filters)
	if not jobs:
		return get_columns(), [], ""

	names = [job.name for job in jobs]
	estimates = get_estimates(names)
	actuals = get_actuals(names, filters)

	data = []
	for job in jobs:
		estimate = estimates.get(job.name, {})
		actual = actuals.get(job.name, {})

		est_income = flt(estimate.get("income"))
		est_expense = flt(estimate.get("expense"))
		act_income = flt(actual.get("income"))
		act_expense = flt(actual.get("expense"))
		est_profit = est_income - est_expense
		act_profit = act_income - act_expense

		last_posting = actual.get("last_posting")
		row = {
			"operation": job.name,
			"date": job.date,
			"customer": job.customer,
			"branch": job.branch,
			"mode_of_shipment": job.mode_of_shipment,
			"status": job.operations_status,
			"estimated_income": est_income,
			"estimated_expense": est_expense,
			"estimated_profit": est_profit,
			"actual_income": act_income,
			"actual_expense": act_expense,
			"actual_profit": act_profit,
			# Positive means the job beat its estimate.
			"variance": act_profit - est_profit,
			# Whether anything has been billed at all. Without this a job that has
			# cost booked and no invoice yet shows a large red loss, and reads
			# identically to one that was billed and genuinely lost money — the
			# two need entirely different follow-up. 19 of 262 rows in a recent
			# period were the first kind.
			"billed": 1 if act_income else 0,
			"variance_pct": (
				(act_profit - est_profit) / abs(est_profit) * 100 if est_profit else None
			),
			"last_posting": last_posting,
			# A job whose ledger caught up after the job's own date. Not an
			# error — it is normal, and it is what makes a period's actuals move
			# after the fact.
			"late_posting": 1 if (last_posting and job.date and last_posting > job.date) else 0,
		}

		if filters.get("only_with_variance") and not row["variance"]:
			continue
		if filters.get("only_untagged") and (act_income or act_expense):
			continue

		data.append(row)

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


def get_jobs(filters):
	"""Jobs in scope, before any ledger is looked at.

	On a Job Date basis the period selects the jobs. On a Posting Date basis it
	does not — the postings do — so the job set is left unbounded here and the
	period is applied to the ledger instead.
	"""
	conditions = ["ops.is_trashed != 1"]
	values = {}

	if filters.get("company"):
		conditions.append("ops.company = %(company)s")
		values["company"] = filters.company

	if filters.get("branch"):
		conditions.append("ops.branch = %(branch)s")
		values["branch"] = filters.branch

	# LIKE rather than `=` on these two so a caller can pass a partial. A Link
	# filter from the desk sends an exact value, and LIKE with no wildcard is an
	# exact match, so both callers get what they expect.
	if filters.get("customer"):
		conditions.append("ops.customer LIKE %(customer)s")
		values["customer"] = filters.customer

	if filters.get("job"):
		conditions.append("ops.name LIKE %(job)s")
		values["job"] = filters.job

	if filters.get("mode_of_shipment"):
		conditions.append("ops.mode_of_shipment = %(mode_of_shipment)s")
		values["mode_of_shipment"] = filters.mode_of_shipment

	if not filters.get("include_open"):
		conditions.append("ops.operations_status != 'OPEN'")

	if filters.get("date_basis") != "Posting Date":
		if filters.get("from_date"):
			conditions.append("ops.date >= %(from_date)s")
			values["from_date"] = filters.from_date
		if filters.get("to_date"):
			conditions.append("ops.date <= %(to_date)s")
			values["to_date"] = filters.to_date

	return frappe.db.sql(
		"""
		SELECT ops.name, ops.date, ops.customer, ops.branch,
		       ops.operations_status, ops.mode_of_shipment
		FROM `tabOperations` ops
		WHERE {conditions}
		ORDER BY ops.date DESC, ops.name DESC
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)


def get_estimates(names):
	"""Estimated income and expense, from the job's own cost sheet.

	`rate` is the sell side of a `Cost Table` row and `cost` the buy side.
	"""
	rows = frappe.db.sql(
		"""
		SELECT ct.parent AS job, SUM(ct.rate) AS income, SUM(ct.cost) AS expense
		FROM `tabCost Table` ct
		WHERE ct.parenttype = 'Operations' AND ct.parent IN %(names)s
		GROUP BY ct.parent
		""",
		{"names": names},
		as_dict=True,
	)
	return {row.job: row for row in rows}


def get_actuals(names, filters):
	"""Actual income and expense, from the ledger, matched by Project.

	A GL Entry with no job in its `project` field never reaches this report —
	the job then shows a blank actual, which is indistinguishable from one that
	genuinely earned nothing. Check the tagging before reading a blank as a loss.
	"""
	conditions = [
		"gle.is_cancelled = 0",
		"gle.project IN %(names)s",
		"acc.account_type IN %(account_types)s",
	]
	values = {
		"names": names,
		"account_types": INCOME_ACCOUNT_TYPES + EXPENSE_ACCOUNT_TYPES,
		"income_types": INCOME_ACCOUNT_TYPES,
		"expense_types": EXPENSE_ACCOUNT_TYPES,
	}

	if filters.get("company"):
		conditions.append("gle.company = %(company)s")
		values["company"] = filters.company

	# On a Posting Date basis the period bounds the ledger. On a Job Date basis
	# it does not — clipping the postings would hide exactly the late ones the
	# comparison exists to show.
	if filters.get("date_basis") == "Posting Date":
		if filters.get("from_date"):
			conditions.append("gle.posting_date >= %(from_date)s")
			values["from_date"] = filters.from_date
		if filters.get("to_date"):
			conditions.append("gle.posting_date <= %(to_date)s")
			values["to_date"] = filters.to_date

	rows = frappe.db.sql(
		"""
		SELECT
			gle.project AS job,
			SUM(CASE WHEN acc.account_type IN %(income_types)s
			         THEN gle.credit - gle.debit ELSE 0 END) AS income,
			SUM(CASE WHEN acc.account_type IN %(expense_types)s
			         THEN gle.debit - gle.credit ELSE 0 END) AS expense,
			MAX(gle.posting_date) AS last_posting
		FROM `tabGL Entry` gle
		INNER JOIN `tabAccount` acc ON acc.name = gle.account
		WHERE {conditions}
		GROUP BY gle.project
		""".format(conditions=" AND ".join(conditions)),
		values,
		as_dict=True,
	)
	return {row.job: row for row in rows}


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
