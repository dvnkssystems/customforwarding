# Copyright (c) 2026, DVNKS Systems and contributors
"""Sales Invoice rules for freight billing."""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.nestedset import get_ancestors_of

OVERSEAS_CUSTOMER_GROUP = "OVERSEAS"


def enforce_overseas_zero_rating(doc, method=None):
	"""An invoice for an overseas customer may not carry VAT.

	The Tax Rule added by the `create_overseas_tax_rule` patch selects the
	zero-rated template on its own for customers in the OVERSEAS group, and this
	stops someone swapping it for a VAT-bearing one by hand.

	A customer can also be overseas by address without being in that group, and
	no Tax Rule fires for them: a Tax Rule matches one country exactly, so "not
	Saudi Arabia" would need a rule per country and would bill 15% the first time
	someone trades with a country nobody added. For those the template is not
	chosen automatically, so the message names the one to pick.
	"""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
		return

	if not is_overseas_customer(doc.customer, doc.customer_group, doc.company):
		return

	charged = [row for row in doc.get("taxes") or [] if flt(row.rate) or flt(row.tax_amount)]
	if not charged:
		return

	template = zero_rated_template(doc.company)
	remedy = _("Use the {0} template instead.").format(frappe.bold(template)) if template else ""

	frappe.throw(
		_("{0} is an overseas customer, so this invoice must be zero-rated. Remove the VAT charged on: {1}. {2}").format(
			frappe.bold(doc.customer_name or doc.customer),
			", ".join(frappe.bold(row.description or row.account_head) for row in charged),
			remedy,
		).strip(),
		title=_("Zero-rated customer"),
	)


def is_overseas_customer(customer, customer_group=None, company=None):
	"""Overseas by customer group or by address country — both, not either alone.

	Neither signal stands on its own here. Of the ten customers in the OVERSEAS
	group, one carries a Saudi address and three carry no address at all; and a
	customer nobody put in the group can still sit in another country. So the
	group catches what the address misses, and the address catches what the group
	misses.
	"""
	group = customer_group or frappe.db.get_value("Customer", customer, "customer_group")
	if is_overseas_group(group):
		return True

	# Without a company country there is nothing to be overseas of.
	home = frappe.db.get_value("Company", company, "country") if company else None
	if not home:
		return False

	country = customer_country(customer)
	return bool(country) and country != home


def is_overseas_group(group):
	if not group:
		return False
	if group == OVERSEAS_CUSTOMER_GROUP:
		return True
	return OVERSEAS_CUSTOMER_GROUP in get_ancestors_of("Customer Group", group)


def customer_country(customer):
	"""The customer's country: the primary address first, then any address of theirs.

	Deliberately does not insist on a Shipping address. Only three of the 247
	addresses on this site are Shipping and 209 are Billing, so requiring the
	shipping type would find nothing for almost every customer.
	"""
	if not customer:
		return None

	primary = frappe.db.get_value("Customer", customer, "customer_primary_address")
	if primary:
		country = frappe.db.get_value("Address", primary, "country")
		if country:
			return country

	linked = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
		pluck="parent",
	)
	for name in linked:
		country = frappe.db.get_value("Address", name, "country")
		if country:
			return country

	return None


def zero_rated_template(company):
	"""The company's zero-rated sales template, found the way the patch found it."""
	if not company:
		return None

	return frappe.db.get_value(
		"Sales Taxes and Charges Template",
		{"company": company, "disabled": 0, "title": ["like", "%VAT Zero%"]},
		"name",
	)
