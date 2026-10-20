# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Conditions behind the Customer 360 banners (spec section 9).

Like the Job 360 banners, each banner is a Job Banner Rule row, here with
Applies To = Customer. The rule picks one of the conditions below by its
condition_key and supplies the message (Jinja), action, colour and priority,
so wording, order and on/off change without code. The seeded rules C1-C3 are
in forwarding.patches.v1_0.seed_party_banner_rules.

Every condition takes ctx, the dict built by forwarding.api.customer_360:

	kpis		the customer's KPI dict (credit_used, credit_limit, ...)
	currency	company currency the amounts are in
	overdue		[{name, due_date, outstanding}] submitted invoices past due
	expiring_quotes	[{name, validity}] open quotes expiring within QUOTE_EXPIRY_DAYS
	quote_expiry_days	QUOTE_EXPIRY_DAYS, for message templates
	today		date the banners are worked out for
"""

from frappe.utils import flt

from forwarding.banners import format_date  # noqa: F401  (re-exported for callers and tests)
from forwarding.party_360 import evaluate_rules

QUOTE_EXPIRY_DAYS = 3


def over_credit_limit(ctx):
	kpis = ctx["kpis"]
	return flt(kpis.get("credit_limit")) > 0 and flt(kpis.get("credit_used")) > flt(kpis.get("credit_limit"))


def overdue_invoices(ctx):
	return bool(ctx.get("overdue"))


def quote_expiring(ctx):
	return bool(ctx.get("expiring_quotes"))


CONDITIONS = {
	"over_credit_limit": over_credit_limit,
	"overdue_invoices": overdue_invoices,
	"quote_expiring": quote_expiring,
}


def evaluate(ctx):
	"""[{code, priority, colour, message, action}] for every enabled Customer
	rule whose condition holds, lowest priority first."""
	return evaluate_rules("Customer", CONDITIONS, {**ctx, "quote_expiry_days": QUOTE_EXPIRY_DAYS})
