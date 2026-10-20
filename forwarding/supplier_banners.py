# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Conditions behind the Supplier 360 banners.

Each banner is a Job Banner Rule row with Applies To = Supplier. The rule
picks one of the conditions below by its condition_key and supplies the
message (Jinja), action, colour and priority. The seeded rules S1-S3 are in
forwarding.patches.v1_0.seed_party_banner_rules.

Every condition takes ctx, the dict built by forwarding.api.supplier_360:

	kpis		the supplier's KPI dict
	currency	company currency the amounts are in
	overdue		[{name, due_date, outstanding}] submitted bills past due
	unbilled_done	[{doctype, name}] finished services with no supplier invoice
	supplier	the supplier header (status, ...)
	hold_type	ERPNext's Supplier hold type (All / Invoices / Payments)
	release_date	date an on-hold supplier is released, if set
	today		date the banners are worked out for
"""

from forwarding.banners import format_date  # noqa: F401  (re-exported for callers and tests)
from forwarding.party_360 import evaluate_rules


def overdue_payables(ctx):
	return bool(ctx.get("overdue"))


def unbilled_services(ctx):
	return bool(ctx.get("unbilled_done"))


def on_hold_or_blocked(ctx):
	return ctx["supplier"]["status"] in ("On Hold", "Blocked")


CONDITIONS = {
	"overdue_payables": overdue_payables,
	"unbilled_services": unbilled_services,
	"on_hold_or_blocked": on_hold_or_blocked,
}


def evaluate(ctx):
	"""[{code, priority, colour, message, action}] for every enabled Supplier
	rule whose condition holds, lowest priority first."""
	return evaluate_rules("Supplier", CONDITIONS, ctx)
