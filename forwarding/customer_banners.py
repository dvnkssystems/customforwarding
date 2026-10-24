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
	expiring_quotes	[{name, validity}] open quotes expiring within quote_expiry_days
	quote_expiry_days	Party Alert Settings' Quote Expiry Warning (Days), for message templates
	not_invoiced_jobs	[{name, operations_status}] jobs raising job banner B5
			(delivered or ops completed, no invoice)
	expiring_documents	[{document_type, expiry_date, days_left, ...}] party
			documents expiring within document_expiry_days
	expired_documents	the same for documents already expired
	document_expiry_days	Party Alert Settings' Document Expiry Warning (Days)
	today		date the banners are worked out for

C5 (job_not_invoiced), C4 / C6 (party documents expiring / expired) and the
threshold settings come from the Phase 2 spec §6.2; they are provisional and
live in Job Banner Rule / Party Alert Settings, not in code.
"""

from frappe.utils import flt

from forwarding.banners import format_date  # noqa: F401  (re-exported for callers and tests)
from forwarding.party_360 import evaluate_rules

# Fallback only; the live value is Party Alert Settings.quote_expiry_days.
QUOTE_EXPIRY_DAYS = 3


def quote_expiry_days():
	from forwarding.forwarding.doctype.party_alert_settings.party_alert_settings import get_settings

	return get_settings().quote_expiry_days


def over_credit_limit(ctx):
	kpis = ctx["kpis"]
	return flt(kpis.get("credit_limit")) > 0 and flt(kpis.get("credit_used")) > flt(kpis.get("credit_limit"))


def overdue_invoices(ctx):
	return bool(ctx.get("overdue"))


def quote_expiring(ctx):
	return bool(ctx.get("expiring_quotes"))


def job_not_invoiced(ctx):
	"""Any of the customer's jobs raises the job banner B5 condition."""
	return bool(ctx.get("not_invoiced_jobs"))


def party_document_expiring(ctx):
	return bool(ctx.get("expiring_documents"))


def party_document_expired(ctx):
	return bool(ctx.get("expired_documents"))


CONDITIONS = {
	"over_credit_limit": over_credit_limit,
	"overdue_invoices": overdue_invoices,
	"quote_expiring": quote_expiring,
	"job_not_invoiced": job_not_invoiced,
	"party_document_expiring": party_document_expiring,
	"party_document_expired": party_document_expired,
}


def evaluate(ctx):
	"""[{code, priority, colour, message, action}] for every enabled Customer
	rule whose condition holds, lowest priority first."""
	defaults = {
		"quote_expiry_days": quote_expiry_days(),
		"not_invoiced_jobs": [],
		"expiring_documents": [],
		"expired_documents": [],
	}
	return evaluate_rules("Customer", CONDITIONS, {**defaults, **ctx})
