# Copyright (c) 2026, DVNKS Systems and contributors
"""Estimation Vs Actual Summary V3: each job's estimated income and expense
(its rate and cost totals) against the income and expense posted to the
ledger for it, and the variance.

It was a Query Report saved on the site with no filters defined, so any
filter left blank raised KeyError (e.g. 'basis') and the report never ran.
The same query now runs here, with every filter given a value.
"""

import frappe
from frappe import _
from frappe.utils import add_months, getdate, today

QUERY = """
WITH job AS (
	SELECT
		o.name AS operations,
		o.date AS job_date,
		o.customer AS customer,
		o.branch AS branch,
		o.operations_status AS status,
		SUM(CASE WHEN a.root_type = 'Income'  THEN g.credit - g.debit ELSE 0 END) AS act_income,
		SUM(CASE WHEN a.root_type = 'Expense' THEN g.debit - g.credit ELSE 0 END) AS act_expense,
		COALESCE(CAST(NULLIF(TRIM(o.total_rate), '') AS DECIMAL(18,4)), 0) AS est_income,
		COALESCE(CAST(NULLIF(TRIM(o.total_cost), '') AS DECIMAL(18,4)), 0) AS est_expense,
		MAX(g.posting_date) AS last_posting,
		COUNT(g.name) AS gl_rows
	FROM `tabOperations` o
	LEFT JOIN `tabGL Entry` g
		ON  g.project = o.name
		AND g.is_cancelled = 0
		AND g.account IN (
			SELECT name FROM `tabAccount`
			WHERE account_type IN ('Income Account', 'Cost of Goods Sold')
		)
		AND (%(basis)s = 'Job Date' OR g.posting_date BETWEEN %(from_date)s AND %(to_date)s)
	LEFT JOIN `tabAccount` a ON a.name = g.account
	WHERE o.docstatus != 2
		AND (%(company)s    IS NULL OR o.company  = %(company)s)
		AND (%(customer)s   IS NULL OR o.customer = %(customer)s)
		AND (%(branch)s     IS NULL OR o.branch   = %(branch)s)
		AND (%(operations)s IS NULL OR o.name     = %(operations)s)
		AND (
				(%(basis)s = 'Job Date'     AND o.date BETWEEN %(from_date)s AND %(to_date)s)
			 OR (%(basis)s = 'Posting Date' AND g.name IS NOT NULL)
		)
	GROUP BY o.name, o.date, o.customer, o.branch, o.operations_status, o.total_rate, o.total_cost
)
SELECT
	operations,
	job_date,
	customer,
	branch,
	status,
	ROUND(est_income, 2) AS est_income,
	ROUND(est_expense, 2) AS est_expense,
	ROUND(est_income - est_expense, 2) AS est_pnl,
	ROUND(act_income, 2) AS act_income,
	ROUND(act_expense, 2) AS act_expense,
	ROUND(act_income - act_expense, 2) AS act_pnl,
	ROUND((act_income - act_expense) - (est_income - est_expense), 2) AS variance,
	CASE WHEN (est_income - est_expense) <> 0
	     THEN ROUND(((act_income - act_expense) - (est_income - est_expense))
	                / ABS(est_income - est_expense) * 100, 1)
	END AS variance_pct,
	last_posting,
	gl_rows
FROM job
ORDER BY job_date, operations
"""

BASES = ("Job Date", "Posting Date")


def execute(filters=None):
	return columns(), frappe.db.sql(QUERY, values(filters), as_dict=True)


def values(filters):
	"""Every placeholder of the query, a blank one as NULL ("any")."""
	f = frappe._dict(filters or {})
	to_date = getdate(f.to_date or today())
	from_date = getdate(f.from_date or add_months(to_date, -1))
	if from_date > to_date:
		frappe.throw(_("From Date must be before To Date."))
	return {
		"company": f.company or None,
		"customer": f.customer or None,
		"branch": f.branch or None,
		"operations": f.operations or None,
		"basis": f.basis if f.basis in BASES else "Job Date",
		"from_date": from_date,
		"to_date": to_date,
	}


def columns():
	def col(fieldname, label, fieldtype, width, options=None):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "options": options, "width": width}

	return [
		col("operations", "Operations", "Link", 150, "Operations"),
		col("job_date", "Job Date", "Date", 95),
		col("customer", "Customer", "Link", 230, "Customer"),
		col("branch", "Branch", "Link", 100, "Branch"),
		col("status", "Status", "Link", 90, "Operations Status"),
		col("est_income", "Estimated Income", "Currency", 140),
		col("est_expense", "Estimated Expense", "Currency", 145),
		col("est_pnl", "Estimated P&L", "Currency", 130),
		col("act_income", "Actual Income", "Currency", 130),
		col("act_expense", "Actual Expense", "Currency", 135),
		col("act_pnl", "Actual P&L", "Currency", 120),
		col("variance", "Variance", "Currency", 110),
		col("variance_pct", "Variance %", "Percent", 100),
		col("last_posting", "Last Posting", "Date", 105),
		col("gl_rows", "GL Rows", "Int", 80),
	]
