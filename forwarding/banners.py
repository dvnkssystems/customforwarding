# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Conditions behind the Job 360 banners.

A Job Banner Rule with Applies To = Operations picks one of these by its
condition_key and supplies the message, action, colour and priority, so the
wording and order can change without code. Adding a new kind of check means
adding a function here and its key to the rule's Condition options. Customer
and Supplier rules pick theirs from customer_banners / supplier_banners.

Each function takes the job (the Operations document) and ctx, the job's KPI
dict from forwarding.api.job_360 plus:

	custom_clearance_count	linked Custom Clearance records
	overdue_invoices	names of submitted Sales Invoices past due with money owed
	today			date the banners are worked out for
"""

import frappe
from frappe.utils import cint, flt, getdate, nowdate

# Statuses compared in lower case, so "OPEN" and "Open" match.
FINISHED = {"delivered", "ops completed", "closed"}
BILLABLE = {"delivered", "ops completed"}
INACTIVE = {"closed", "cancelled"}


def _status(job):
	return (job.get("operations_status") or "").strip().lower()


def _today(ctx):
	return getdate(ctx.get("today") or nowdate())


def _active(job):
	"""A closed or cancelled job has no operational work left to prompt for."""
	return job.get("docstatus") != 2 and _status(job) not in INACTIVE


def docs_pending(job, ctx):
	return _active(job) and cint(ctx.get("docs_received")) < cint(ctx.get("docs_total"))


def atd_missing(job, ctx):
	return bool(
		_active(job)
		and job.get("etd_date")
		and getdate(job.get("etd_date")) <= _today(ctx)
		and not job.get("atd_date")
	)


def ata_missing(job, ctx):
	"""Only once the cargo has left (ATD recorded) and the ETA has passed
	(R3-55): before departure there is nothing to arrive yet."""
	return bool(
		_active(job)
		and job.get("atd_date")
		and job.get("eta_date")
		and getdate(job.get("eta_date")) <= _today(ctx)
		and not job.get("ata_date")
	)


def free_time_expiring(job, ctx):
	"""Free time runs out within three days. A recorded delivery clears it
	(A-22: Record delivery)."""
	days = ctx.get("free_days_left")
	return (
		days is not None
		and days <= 3
		and not job.get("delivery_date")
		and _status(job) not in FINISHED
		and _status(job) not in INACTIVE
	)


def not_invoiced(job, ctx):
	return _status(job) in BILLABLE and (job.get("billing_status") or "No Invoice") == "No Invoice"


def invoice_overdue(job, ctx):
	return bool(ctx.get("overdue_invoices"))


def _offers(job, ctx, service_type):
	"""Whether the job holds a service of this type within its scope (M-05,
	M-06). ctx carries the job's service types (forwarding.services); without
	them the Activity & Services tick-box decides."""
	types = ctx.get("service_types")
	if types is None:
		from forwarding.services import SERVICE_TYPE_FIELD

		return bool(cint(job.get(SERVICE_TYPE_FIELD[service_type])))
	return service_type in types


def customs_missing(job, ctx):
	"""The job holds a Customs Clearance service, but no Custom Clearance
	record has been created for it yet."""
	return bool(
		_active(job)
		and _offers(job, ctx, "Customs Clearance")
		and not cint(ctx.get("custom_clearance_count"))
	)


def credit_hold(job, ctx):
	return _status(job) == "on hold"


def has_estimate(job):
	"""At least one cost sheet row with an Est. Selling above zero (M-02)."""
	return any(flt(row.get("rate")) > 0 for row in job.get("cost_table") or [])


def estimate_missing(job, ctx):
	"""A draft job with no estimate yet. It cannot be submitted until it has
	one (Operations.before_submit); a submitted job's cost sheet is locked, so
	there is nothing left to prompt for there."""
	return cint(job.get("docstatus")) == 0 and _active(job) and not has_estimate(job)


CONDITIONS = {
	"docs_pending": docs_pending,
	"atd_missing": atd_missing,
	"ata_missing": ata_missing,
	"free_time_expiring": free_time_expiring,
	"not_invoiced": not_invoiced,
	"invoice_overdue": invoice_overdue,
	"customs_missing": customs_missing,
	"credit_hold": credit_hold,
	"estimate_missing": estimate_missing,
}


def conditions_for(applies_to):
	"""The condition registry a rule for applies_to picks its condition_key from."""
	if applies_to == "Customer":
		from forwarding.customer_banners import CONDITIONS as customer

		return customer
	if applies_to == "Supplier":
		from forwarding.supplier_banners import CONDITIONS as supplier

		return supplier
	return CONDITIONS


def _free_time_colour(job, ctx, default):
	return "critical" if (ctx.get("free_days_left") or 0) <= 0 else "warning"


# A condition listed here decides its own colour; the rule's colour is the
# fallback for everything else.
COLOURS = {
	"free_time_expiring": _free_time_colour,
}


def format_date(value):
	"""19 Oct 2026, whatever the system date format. Offered to message
	templates as format_date()."""
	if not value:
		return ""
	d = getdate(value)
	return f"{d.day} {d.strftime('%b %Y')}"


def _free_time_state(job, ctx):
	days = ctx.get("free_days_left") or 0
	return "expired" if days <= 0 else "last day" if days == 1 else "soon"


# What a dismissed banner is waiting to change (A-22): one listed here comes
# back when this changes; any other when its message does.
FINGERPRINTS = {
	"invoice_overdue": lambda job, ctx: ",".join(sorted(ctx.get("overdue_invoices") or [])),
	"free_time_expiring": _free_time_state,
}

# Banners that act in place (A-22): their buttons, first is the main one.
ACTIONS = {
	"invoice_overdue": ["record_payment", "send_reminder"],
	"free_time_expiring": ["record_delivery", "request_extension"],
}


def get_rules(applies_to="Operations"):
	"""Enabled rules for one page, lowest priority first."""
	return frappe.get_all(
		"Job Banner Rule",
		filters={"enabled": 1, "applies_to": applies_to},
		fields=[
			"rule_code",
			"label",
			"priority",
			"condition_key",
			"message_template",
			"action",
			"colour",
			"show_on_worklist",
		],
		order_by="priority asc, rule_code asc",
	)


def evaluate(job, ctx, rules=None):
	"""Every enabled rule whose condition holds, lowest priority first.
	A cancelled job has nothing left to act on: no banners (R2-10), and so
	no worklist entries either (R2-12)."""
	if cint(job.get("docstatus")) == 2:
		return []
	banners = []
	for rule in get_rules() if rules is None else rules:
		condition = CONDITIONS.get(rule.condition_key)
		if not condition:
			continue
		try:
			if not condition(job, ctx):
				continue
			message = frappe.render_template(
				rule.message_template or "", {"doc": job, "ctx": ctx, "format_date": format_date}
			)
		except Exception:
			# One bad template must not take the whole job page down.
			frappe.log_error(
				title=f"Job banner {rule.rule_code} failed",
				reference_doctype="Job Banner Rule",
				reference_name=rule.rule_code,
			)
			continue

		from forwarding.banner_dismissal import fingerprint_of

		colour_fn = COLOURS.get(rule.condition_key)
		fingerprint = FINGERPRINTS.get(rule.condition_key)
		actions = ACTIONS.get(rule.condition_key) or ([rule.action] if rule.action else [])
		overdue = ctx.get("overdue_invoices") or []
		banners.append(
			{
				"rule_code": rule.rule_code,
				"priority": cint(rule.priority),
				"colour": colour_fn(job, ctx, rule.colour) if colour_fn else (rule.colour or "info"),
				"message": message.strip(),
				"action": actions[0] if actions else None,
				"actions": actions,
				"fingerprint": fingerprint_of(fingerprint(job, ctx) if fingerprint else message.strip()),
				# The invoice an overdue banner's buttons act on: the first overdue.
				"invoice": overdue[0] if rule.condition_key == "invoice_overdue" and overdue else None,
			}
		)
	return banners
