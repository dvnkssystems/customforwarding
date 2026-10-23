# Copyright (c) 2026, DVNKS Systems and contributors
"""Stop addresses printing "None" (QA Round 2, R2-04).

The site's "Saudi Arabia" Address Template has a line that is just
`{{ custom_area }}` with no guard, so an address with no area renders the
text "None" ("Surat<br> None Saudi Arabia" - read as "Surat, None Saudi
Arabia" on the invoice). Every Address Template line that is a bare
`{{ field }}` gets an `{% if field %}` guard and its own line break.

Rendered addresses are stored as text on documents. They are re-rendered
from the (now fixed) template only where that is safe:
- draft Sales Invoices (address_display, company_address_display,
  shipping_address), and
- Customer.primary_address.
Submitted and cancelled invoices keep the text they were issued with (they
may already be reported to ZATCA); the "Freight Tax Invoice" print format
drops "None" parts when it prints them.

Data only. Idempotent.
"""

import re

import frappe
from frappe.contacts.doctype.address.address import get_address_display

BARE_LINE = re.compile(r"^([ \t]*)\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}[ \t]*$", re.MULTILINE)
INVOICE_FIELDS = (
	("customer_address", "address_display"),
	("company_address", "company_address_display"),
	("shipping_address_name", "shipping_address"),
)


def guard_bare_fields(template):
	return BARE_LINE.sub(r"\1{% if \2 %}{{ \2 }}<br>{% endif -%}", template or "")


def execute():
	fix_templates()
	rerender_draft_invoices()
	rerender_customers()


def fix_templates():
	for t in frappe.get_all("Address Template", fields=["name", "template"]):
		fixed = guard_bare_fields(t.template)
		if fixed != (t.template or ""):
			frappe.db.set_value("Address Template", t.name, "template", fixed)
	frappe.clear_cache()


def _has_none(text):
	return text and re.search(r"(^|>|\s)None(\s|<|,|$)", text)


def rerender_draft_invoices():
	meta = frappe.get_meta("Sales Invoice")
	pairs = [(link, display) for link, display in INVOICE_FIELDS if meta.has_field(link) and meta.has_field(display)]
	fields = ["name"] + [f for pair in pairs for f in pair]
	for si in frappe.get_all("Sales Invoice", filters={"docstatus": 0}, fields=fields):
		updates = {}
		for link, display in pairs:
			if si.get(link) and _has_none(si.get(display)):
				updates[display] = get_address_display(si.get(link))
		if updates:
			frappe.db.set_value("Sales Invoice", si.name, updates, update_modified=False)


def rerender_customers():
	for c in frappe.get_all(
		"Customer",
		filters={"customer_primary_address": ["is", "set"], "primary_address": ["like", "%None%"]},
		fields=["name", "customer_primary_address", "primary_address"],
	):
		if _has_none(c.primary_address):
			frappe.db.set_value(
				"Customer",
				c.name,
				"primary_address",
				get_address_display(c.customer_primary_address),
				update_modified=False,
			)
