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
	expiring_rates	[{name, item_code, valid_upto}] buying Item Prices for the
			supplier ending within rate_expiry_days (not yet ended)
	rate_expiry_days	Party Alert Settings' Rate Expiry Warning (Days)
	cost_variance	the Cost variance KPI dict (jobs_over_estimate, threshold, ...)
	jobs_over	[{job, estimated, invoiced, variance_pct}] jobs over the threshold
	expiring_documents	[{document_type, expiry_date, days_left, ...}] party
			documents expiring within document_expiry_days
	expired_documents	the same for documents already expired
	document_expiry_days	Party Alert Settings' Document Expiry Warning (Days)
	today		date the banners are worked out for

S4 (rate_expiring), S6 (over_estimate) and S7 / S8 (party documents
expiring / expired; the spec's S2 / S3) come from the Phase 2 spec §6.2;
they are provisional, so their wording lives in Job Banner Rule and their
thresholds in Party Alert Settings.
"""

from forwarding.banners import format_date  # noqa: F401  (re-exported for callers and tests)
from forwarding.party_360 import evaluate_rules


def overdue_payables(ctx):
	return bool(ctx.get("overdue"))


def unbilled_services(ctx):
	return bool(ctx.get("unbilled_done"))


def on_hold_or_blocked(ctx):
	return ctx["supplier"]["status"] in ("On Hold", "Blocked")


def rate_expiring(ctx):
	return bool(ctx.get("expiring_rates"))


def over_estimate(ctx):
	return bool(ctx.get("jobs_over"))


def party_document_expiring(ctx):
	return bool(ctx.get("expiring_documents"))


def party_document_expired(ctx):
	return bool(ctx.get("expired_documents"))


CONDITIONS = {
	"overdue_payables": overdue_payables,
	"unbilled_services": unbilled_services,
	"on_hold_or_blocked": on_hold_or_blocked,
	"rate_expiring": rate_expiring,
	"over_estimate": over_estimate,
	"party_document_expiring": party_document_expiring,
	"party_document_expired": party_document_expired,
}


def evaluate(ctx):
	"""[{code, priority, colour, message, action}] for every enabled Supplier
	rule whose condition holds, lowest priority first."""
	return evaluate_rules("Supplier", CONDITIONS, ctx)
