# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Estimation vs Actual figures, per job.

One implementation behind two screens: the Estimation vs Actual report
(`Estimation VS Actual Summary Report_-NEW`) and the figures at the top of the
Charges tab on Job 360. Both call `figures()`, so a job's numbers on its own
page always equal its row in the report (M-03).

The estimate is the job's cost sheet (`Cost Table`), typed in when the job is
opened (M-01): `rate` is Est. Selling, `cost` Est. Cost. The actuals come from
the ledger, matched to the job by the GL Entry's Project.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

# The account types that make up a job's revenue and its cost of sale. Kept
# exactly as the original report had them so the figures stay comparable —
# widening this to include every Expense Account would change every row.
INCOME_ACCOUNT_TYPES = ("Income Account",)
EXPENSE_ACCOUNT_TYPES = ("Cost of Goods Sold",)


def figures(filters=None):
	"""One row per job in scope: estimated and actual income, expense, profit
	and the variance between them. See `get_jobs` for the filters."""
	filters = frappe._dict(filters or {})
	jobs = get_jobs(filters)
	if not jobs:
		return []

	names = [job.name for job in jobs]
	estimates = get_estimates(names)
	actuals = get_actuals(names, filters)

	data = []
	for job in jobs:
		row = job_row(job, estimates.get(job.name, {}), actuals.get(job.name, {}))
		if filters.get("only_with_variance") and not row["variance"]:
			continue
		if filters.get("only_untagged") and (row["actual_income"] or row["actual_expense"]):
			continue
		data.append(row)
	return data


def job_figures(job):
	"""The report's row for one job (an Operations name or document), with no
	period applied: everything estimated and everything posted so far."""
	name = job if isinstance(job, str) else job.name
	company = frappe.db.get_value("Operations", name, "company")
	rows = figures(
		{
			"company": company,
			"jobs": [name],
			"date_basis": "Job Date",
			"include_open": 1,
			# The job's own page still shows its figures once it is cancelled.
			"include_cancelled": 1,
		}
	)
	return rows[0] if rows else None


def job_row(job, estimate, actual):
	est_income = flt(estimate.get("income"))
	est_expense = flt(estimate.get("expense"))
	act_income = flt(actual.get("income"))
	act_expense = flt(actual.get("expense"))
	est_profit = est_income - est_expense
	act_profit = act_income - act_expense
	variance = act_profit - est_profit

	last_posting = actual.get("last_posting")
	return {
		"operation": job.name,
		"date": job.date,
		"customer": job.customer,
		"branch": job.branch,
		"mode_of_shipment": job.mode_of_shipment,
		# A cancelled job reads as Cancelled whatever its operations status
		# said when it was cancelled (M-19).
		"status": "Cancelled" if is_cancelled(job) else job.operations_status,
		"docstatus": cint(job.docstatus),
		"estimated_income": est_income,
		"estimated_expense": est_expense,
		"estimated_profit": est_profit,
		"actual_income": act_income,
		"actual_expense": act_expense,
		"actual_profit": act_profit,
		# Positive means the job beat its estimate.
		"variance": variance,
		# Whether anything has been billed at all. Without this a job that has
		# cost booked and no invoice yet shows a large red loss, and reads
		# identically to one that was billed and genuinely lost money — the
		# two need entirely different follow-up.
		"billed": 1 if act_income else 0,
		# What the Variance column says instead of a number until the job has
		# been billed (R3-59): an open job is not a loss. Such a job counts as
		# neither beating nor falling short of its estimate.
		"variance_label": None if act_income else _("Not billed yet"),
		# A percentage of the estimated profit only means something when that
		# profit is positive: against a loss it reads backwards (+300% on a job
		# estimated at -1,000), and against zero it is undefined (M-20).
		"variance_pct": variance / est_profit * 100 if est_profit > 0 and act_income else None,
		"last_posting": last_posting,
		# A job whose ledger caught up after the job's own date. Not an
		# error — it is normal, and it is what makes a period's actuals move
		# after the fact.
		"late_posting": 1 if (last_posting and job.date and last_posting > job.date) else 0,
	}


def is_cancelled(job):
	return cint(job.docstatus) == 2 or (job.operations_status or "") == "Cancelled"


def get_jobs(filters):
	"""Jobs in scope, before any ledger is looked at.

	On a Job Date basis the period selects the jobs. On a Posting Date basis it
	does not — the postings do — so the job set is left unbounded here and the
	period is applied to the ledger instead.

	Cancelled jobs are left out unless `include_cancelled` is set (M-19).
	"""
	conditions = ["ops.is_trashed != 1"]
	values = {}

	# Cancelled is the document cancelled, or its status set to Cancelled — the
	# worklist leaves out both too.
	if not filters.get("include_cancelled"):
		conditions.append("ops.docstatus != 2 AND IFNULL(ops.operations_status, '') != 'Cancelled'")

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

	# Exact names, for callers that know the jobs (Job 360).
	if filters.get("jobs"):
		conditions.append("ops.name IN %(jobs)s")
		values["jobs"] = tuple(filters.jobs)

	if filters.get("mode_of_shipment"):
		conditions.append("ops.mode_of_shipment = %(mode_of_shipment)s")
		values["mode_of_shipment"] = filters.mode_of_shipment

	if not filters.get("include_open"):
		conditions.append("ops.operations_status != 'Open'")

	if filters.get("date_basis") != "Posting Date":
		if filters.get("from_date"):
			conditions.append("ops.date >= %(from_date)s")
			values["from_date"] = filters.from_date
		if filters.get("to_date"):
			conditions.append("ops.date <= %(to_date)s")
			values["to_date"] = filters.to_date

	return frappe.db.sql(
		"""
		SELECT ops.name, ops.date, ops.customer, ops.branch, ops.docstatus,
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

	`rate` is the sell side of a `Cost Table` row (Est. Selling) and `cost` the
	buy side (Est. Cost).
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
