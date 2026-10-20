# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Banners on the Customer 360 page (spec section 9, provisional).

Unlike the Job 360 banners these are not configurable yet: each one is an
entry in BANNERS with a code, colour, action, the condition that shows it and
the function that writes its message. If the rules settle, they can move to a
DocType the way Job Banner Rule did.

Every function takes ctx, the dict built by forwarding.api.customer_360:

	kpis		the customer's KPI dict (credit_used, credit_limit, ...)
	currency	company currency the amounts are in
	overdue		[{name, due_date, outstanding}] submitted invoices past due
	expiring_quotes	[{name, validity}] open quotes expiring within QUOTE_EXPIRY_DAYS
	today		date the banners are worked out for
"""

import frappe
from frappe import _
from frappe.utils import flt

from forwarding.banners import format_date
from forwarding.party_360 import evaluate_banners, money

QUOTE_EXPIRY_DAYS = 3


# -- C1 over credit limit ----------------------------------------------------------


def over_credit_limit(ctx):
	kpis = ctx["kpis"]
	return flt(kpis.get("credit_limit")) > 0 and flt(kpis.get("credit_used")) > flt(kpis.get("credit_limit"))


def over_credit_limit_message(ctx):
	kpis = ctx["kpis"]
	return _("Over credit limit: {0} used of {1} ({2}%)").format(
		money(kpis["credit_used"], ctx), money(kpis["credit_limit"], ctx), flt(kpis.get("credit_pct"), 0)
	)


# -- C2 overdue invoices ------------------------------------------------------------


def overdue_invoices(ctx):
	return bool(ctx.get("overdue"))


def overdue_invoices_message(ctx):
	rows = ctx["overdue"]
	oldest = min(r["due_date"] for r in rows)
	total = sum(flt(r["outstanding"]) for r in rows)
	if len(rows) == 1:
		return _("Invoice {0} is overdue: {1} owed since {2}").format(
			rows[0]["name"], money(total, ctx), format_date(oldest)
		)
	return _("{0} invoices overdue: {1} owed, oldest due {2}").format(
		len(rows), money(total, ctx), format_date(oldest)
	)


# -- C3 quote expiring --------------------------------------------------------------


def quote_expiring(ctx):
	return bool(ctx.get("expiring_quotes"))


def quote_expiring_message(ctx):
	rows = sorted(ctx["expiring_quotes"], key=lambda r: (r["validity"], r["name"]))
	if len(rows) == 1:
		return _("Quote {0} expires {1}").format(rows[0]["name"], format_date(rows[0]["validity"]))
	return _("{0} quotes expire within {1} days: {2}").format(
		len(rows),
		QUOTE_EXPIRY_DAYS,
		", ".join(f"{r['name']} ({format_date(r['validity'])})" for r in rows),
	)


# Order here is the order on the page.
BANNERS = (
	{
		"code": "C1",
		"key": "over_credit_limit",
		"colour": "critical",
		"action": "view_invoices",
		"condition": over_credit_limit,
		"message": over_credit_limit_message,
	},
	{
		"code": "C2",
		"key": "overdue_invoices",
		"colour": "critical",
		"action": "view_invoices",
		"condition": overdue_invoices,
		"message": overdue_invoices_message,
	},
	{
		"code": "C3",
		"key": "quote_expiring",
		"colour": "warning",
		"action": "view_quotes",
		"condition": quote_expiring,
		"message": quote_expiring_message,
	},
)


def evaluate(ctx):
	"""[{code, colour, message, action}] for every banner whose condition holds."""
	return evaluate_banners(BANNERS, ctx, "Customer")
