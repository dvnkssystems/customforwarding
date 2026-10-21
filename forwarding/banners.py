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
from frappe.utils import cint, getdate, nowdate

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
	return bool(
		_active(job)
		and job.get("eta_date")
		and getdate(job.get("eta_date")) <= _today(ctx)
		and not job.get("ata_date")
	)


def free_time_expiring(job, ctx):
	days = ctx.get("free_days_left")
	return days is not None and days <= 3 and _status(job) not in FINISHED and _status(job) not in INACTIVE


def not_invoiced(job, ctx):
	return _status(job) in BILLABLE and (job.get("billing_status") or "No Invoice") == "No Invoice"


def invoice_overdue(job, ctx):
	return bool(ctx.get("overdue_invoices"))


def customs_missing(job, ctx):
	"""Customs Clearance is ticked under Activity & Services, but no Custom
	Clearance record has been created for the job yet."""
	return bool(
		_active(job)
		and cint(job.get("svc_customs_clearance"))
		and not cint(ctx.get("custom_clearance_count"))
	)


def credit_hold(job, ctx):
	return _status(job) == "on hold"


CONDITIONS = {
	"docs_pending": docs_pending,
	"atd_missing": atd_missing,
	"ata_missing": ata_missing,
	"free_time_expiring": free_time_expiring,
	"not_invoiced": not_invoiced,
	"invoice_overdue": invoice_overdue,
	"customs_missing": customs_missing,
	"credit_hold": credit_hold,
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
	"""Every enabled rule whose condition holds, lowest priority first."""
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

		colour_fn = COLOURS.get(rule.condition_key)
		banners.append(
			{
				"rule_code": rule.rule_code,
				"priority": cint(rule.priority),
				"colour": colour_fn(job, ctx, rule.colour) if colour_fn else (rule.colour or "info"),
				"message": message.strip(),
				"action": rule.action or None,
			}
		)
	return banners
