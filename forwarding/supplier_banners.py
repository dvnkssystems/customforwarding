# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Banners on the Supplier 360 page (provisional, like customer_banners).

Each banner is an entry in BANNERS with a code, colour, action, the condition
that shows it and the function that writes its message.

Every function takes ctx, the dict built by forwarding.api.supplier_360:

	kpis		the supplier's KPI dict
	currency	company currency the amounts are in
	overdue		[{name, due_date, outstanding}] submitted bills past due
	unbilled_done	[{doctype, name}] finished services with no supplier invoice
	supplier	the supplier header (status, ...)
	hold_type	ERPNext's Supplier hold type (All / Invoices / Payments)
	release_date	date an on-hold supplier is released, if set
	today		date the banners are worked out for
"""

from frappe import _
from frappe.utils import flt

from forwarding.banners import format_date
from forwarding.party_360 import evaluate_banners, money

# -- S1 overdue payables --------------------------------------------------------------


def overdue_payables(ctx):
	return bool(ctx.get("overdue"))


def overdue_payables_message(ctx):
	rows = ctx["overdue"]
	oldest = min(r["due_date"] for r in rows)
	total = sum(flt(r["outstanding"]) for r in rows)
	if len(rows) == 1:
		return _("1 bill overdue: {0}, due {1}").format(money(total, ctx), format_date(oldest))
	return _("{0} bills overdue: {1}, oldest due {2}").format(
		len(rows), money(total, ctx), format_date(oldest)
	)


# -- S2 unbilled services -------------------------------------------------------------


def unbilled_services(ctx):
	return bool(ctx.get("unbilled_done"))


def unbilled_services_message(ctx):
	count = len(ctx["unbilled_done"])
	if count == 1:
		return _("1 service delivered with no supplier invoice")
	return _("{0} services delivered with no supplier invoice").format(count)


# -- S3 on hold or blocked ------------------------------------------------------------


def on_hold_or_blocked(ctx):
	return ctx["supplier"]["status"] in ("On Hold", "Blocked")


def on_hold_or_blocked_message(ctx):
	if ctx["supplier"]["status"] == "Blocked":
		return _("Supplier is blocked")
	hold = ctx.get("hold_type") or "All"
	what = {"Invoices": _("invoices"), "Payments": _("payments")}.get(hold, _("invoices and payments"))
	if ctx.get("release_date"):
		return _("Supplier is on hold for {0} until {1}").format(what, format_date(ctx["release_date"]))
	return _("Supplier is on hold for {0}").format(what)


# Order here is the order on the page.
BANNERS = (
	{
		"code": "S1",
		"key": "overdue_payables",
		"colour": "critical",
		"action": "view_invoices",
		"condition": overdue_payables,
		"message": overdue_payables_message,
	},
	{
		"code": "S2",
		"key": "unbilled_services",
		"colour": "warning",
		"action": "view_services",
		"condition": unbilled_services,
		"message": unbilled_services_message,
	},
	{
		"code": "S3",
		"key": "on_hold_or_blocked",
		"colour": "critical",
		"action": "edit",
		"condition": on_hold_or_blocked,
		"message": on_hold_or_blocked_message,
	},
)


def evaluate(ctx):
	"""[{code, colour, message, action}] for every banner whose condition holds."""
	return evaluate_banners(BANNERS, ctx, "Supplier")
