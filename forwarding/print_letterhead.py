# Copyright (c) 2026, DVNKS Systems and contributors
"""The company letterhead on our own prints.

Frappe draws the Letter Head itself only on its standard layouts. Our print
formats are custom HTML, so each one puts `letter_head` at the top and
`footer()` at the bottom (see the print format JSONs). The Statement of
Account isn't a print format; it calls `company_letterhead()` instead.

The Letter Head's own HTML reads the company details through
`letterhead_company()`, so a change on the Company (VAT, website, address)
shows on every print without editing the Letter Head.
"""

import frappe
from frappe.utils import scrub_urls
from frappe.utils.jinja import render_template


def _default_company():
	return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


def _company_address_line(company):
	"""The company address on one line: street, district, city postal code, province."""
	from frappe.contacts.doctype.address.address import get_company_address

	name = (get_company_address(company) or frappe._dict()).get("company_address")
	if not name:
		return ""
	fields = ["address_line1", "address_line2", "city", "state", "pincode"]
	meta = frappe.get_meta("Address")
	if meta.has_field("custom_building_number"):
		fields.append("custom_building_number")
	a = frappe.db.get_value("Address", name, fields, as_dict=True) or frappe._dict()
	city = " ".join(p for p in (a.city, a.pincode) if p)
	street = " ".join(p for p in (a.get("custom_building_number"), a.address_line1) if p)
	return ", ".join(p for p in (street, a.address_line2, city, a.state) if p)


def letterhead_company(doc=None, company=None):
	"""Company details a Letter Head prints: name, VAT, CR, address, contact."""
	company = company or (doc and doc.get("company")) or _default_company()
	if not company:
		return frappe._dict()
	meta = frappe.get_meta("Company")
	fields = [
		f
		for f in ("company_name", "company_arabic_name", "tax_id", "cr_number", "email", "phone_no", "website")
		if meta.has_field(f)
	]
	c = frappe.db.get_value("Company", company, fields, as_dict=True) or frappe._dict()
	website = (c.get("website") or "").removeprefix("https://").removeprefix("http://").rstrip("/")
	return frappe._dict(
		name=c.get("company_name") or company,
		name_ar=c.get("company_arabic_name") or "",
		tax_id=c.get("tax_id") or "",
		cr=c.get("cr_number") or "",
		email=c.get("email") or "",
		phone=c.get("phone_no") or "",
		website=website,
		address=_company_address_line(company),
	)


def _letter_head_name(company):
	name = frappe.db.get_value("Company", company, "default_letter_head") if company else None
	return name or frappe.db.get_value("Letter Head", {"is_default": 1, "disabled": 0}, "name")


def company_letterhead(company=None):
	"""The default Letter Head as {"header", "footer"} HTML, for pages that
	are not print formats (the Statement of Account)."""
	company = company or _default_company()
	name = _letter_head_name(company)
	if not name:
		return frappe._dict(header="", footer="")
	lh = frappe.db.get_value("Letter Head", name, ["content", "footer"], as_dict=True) or frappe._dict()
	context = {"doc": frappe._dict(company=company)}
	return frappe._dict(
		# Absolute URLs: wkhtmltopdf renders from a temp file, not the site.
		header=scrub_urls(render_template(lh.content, context)) if lh.content else "",
		footer=render_template(lh.footer, context) if (lh.footer or "").strip() else "",
	)
