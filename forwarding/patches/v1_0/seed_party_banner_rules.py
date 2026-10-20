# Copyright (c) 2026, DVNKS Systems and contributors
"""Seed the Customer 360 (C1-C3) and Supplier 360 (S1-S3) banner rules.

These banners used to be hard-coded in customer_banners / supplier_banners.
The templates below write exactly the messages that code wrote, through the
same translatable strings. Like seed_job_banner_rules, a rule is only
inserted when its code is missing, so anything edited on a site is never
overwritten.
"""

import frappe

RULES = [
	# -- Customer 360 -------------------------------------------------------------
	{
		"rule_code": "C1",
		"applies_to": "Customer",
		"label": "Over credit limit",
		"priority": 10,
		"condition_key": "over_credit_limit",
		"action": "view_invoices",
		"colour": "critical",
		"message_template": (
			"{{ _('Over credit limit: {0} used of {1} ({2}%)').format("
			"money(ctx.kpis.credit_used), money(ctx.kpis.credit_limit), flt(ctx.kpis.credit_pct, 0)) }}"
		),
	},
	{
		"rule_code": "C2",
		"applies_to": "Customer",
		"label": "Invoices overdue",
		"priority": 20,
		"condition_key": "overdue_invoices",
		"action": "view_invoices",
		"colour": "critical",
		"message_template": (
			"{% set rows = ctx.overdue %}"
			"{% set oldest = rows|map(attribute='due_date')|min %}"
			"{% set total = rows|map(attribute='outstanding')|map('float')|sum %}"
			"{% if rows|length == 1 %}"
			"{{ _('Invoice {0} is overdue: {1} owed since {2}').format(rows[0].name, money(total), format_date(oldest)) }}"
			"{% else %}"
			"{{ _('{0} invoices overdue: {1} owed, oldest due {2}').format(rows|length, money(total), format_date(oldest)) }}"
			"{% endif %}"
		),
	},
	{
		"rule_code": "C3",
		"applies_to": "Customer",
		"label": "Quote expiring",
		"priority": 30,
		"condition_key": "quote_expiring",
		"action": "view_quotes",
		"colour": "warning",
		"message_template": (
			"{% set rows = ctx.expiring_quotes|sort(attribute='validity,name') %}"
			"{% if rows|length == 1 %}"
			"{{ _('Quote {0} expires {1}').format(rows[0].name, format_date(rows[0].validity)) }}"
			"{% else %}"
			"{% set ns = namespace(quotes='') %}"
			"{% for r in rows %}"
			"{% set ns.quotes = ns.quotes ~ ('' if loop.first else ', ') ~ r.name ~ ' (' ~ format_date(r.validity) ~ ')' %}"
			"{% endfor %}"
			"{{ _('{0} quotes expire within {1} days: {2}').format(rows|length, ctx.quote_expiry_days, ns.quotes) }}"
			"{% endif %}"
		),
	},
	# -- Supplier 360 -------------------------------------------------------------
	{
		"rule_code": "S1",
		"applies_to": "Supplier",
		"label": "Bills overdue",
		"priority": 10,
		"condition_key": "overdue_payables",
		"action": "view_invoices",
		"colour": "critical",
		"message_template": (
			"{% set rows = ctx.overdue %}"
			"{% set oldest = rows|map(attribute='due_date')|min %}"
			"{% set total = rows|map(attribute='outstanding')|map('float')|sum %}"
			"{% if rows|length == 1 %}"
			"{{ _('1 bill overdue: {0}, due {1}').format(money(total), format_date(oldest)) }}"
			"{% else %}"
			"{{ _('{0} bills overdue: {1}, oldest due {2}').format(rows|length, money(total), format_date(oldest)) }}"
			"{% endif %}"
		),
	},
	{
		"rule_code": "S2",
		"applies_to": "Supplier",
		"label": "Services not billed",
		"priority": 20,
		"condition_key": "unbilled_services",
		"action": "view_services",
		"colour": "warning",
		"message_template": (
			"{% set n = ctx.unbilled_done|length %}"
			"{% if n == 1 %}"
			"{{ _('1 service delivered with no supplier invoice') }}"
			"{% else %}"
			"{{ _('{0} services delivered with no supplier invoice').format(n) }}"
			"{% endif %}"
		),
	},
	{
		"rule_code": "S3",
		"applies_to": "Supplier",
		"label": "On hold or blocked",
		"priority": 30,
		"condition_key": "on_hold_or_blocked",
		"action": "edit",
		"colour": "critical",
		"message_template": (
			"{% if ctx.supplier.status == 'Blocked' %}"
			"{{ _('Supplier is blocked') }}"
			"{% else %}"
			"{% set hold = ctx.hold_type or 'All' %}"
			"{% set what = _('invoices') if hold == 'Invoices' else (_('payments') if hold == 'Payments' else _('invoices and payments')) %}"
			"{% if ctx.release_date %}"
			"{{ _('Supplier is on hold for {0} until {1}').format(what, format_date(ctx.release_date)) }}"
			"{% else %}"
			"{{ _('Supplier is on hold for {0}').format(what) }}"
			"{% endif %}"
			"{% endif %}"
		),
	},
]


def execute():
	frappe.reload_doc("forwarding", "doctype", "job_banner_rule")
	for rule in RULES:
		if frappe.db.exists("Job Banner Rule", rule["rule_code"]):
			continue
		frappe.get_doc({"doctype": "Job Banner Rule", "enabled": 1, **rule}).insert(ignore_permissions=True)
