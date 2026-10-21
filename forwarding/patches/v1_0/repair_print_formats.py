# Copyright (c) 2026, DVNKS Systems and contributors
"""Make every Sales Invoice print format produce a PDF.

- Letter Head: an HTML header or footer whose <img> points at a /files/ image
  that is no longer on disk makes wkhtmltopdf refuse the whole PDF ("broken
  image links"), on every document printed with that letter head. The broken
  image is replaced with the company name (header) or dropped (footer).
- The site's own invoice formats ("With Letterhead" and its copies) keep an
  old address block inside an HTML comment. Jinja still runs it, and
  `doc.address` does not exist on Sales Invoice, so rendering fails. The
  commented-out block is removed; the address shown comes from
  address_display as before. The seller VAT number typed into them is
  replaced with the invoice company's Tax ID, and images that are no longer
  on disk are dropped, the header one
  for the company name, as on the letter head. The e-invoice QR image is
  only drawn when the invoice has one.
- "Sales Invoice Print" is a standard format whose template is not in
  ERPNext any more; it is disabled.

Data only, nothing in Frappe or ERPNext is edited. Idempotent.
"""

import os
import re

import frappe

IMG = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
DEAD_ADDRESS_COMMENT = re.compile(r"<!--((?!-->).)*?doc\.address\b,((?!-->).)*?-->", re.DOTALL)
OLD_SELLER_VAT = "311865189200003"
# An unset QR renders as <img src=>, which wkhtmltopdf also calls broken.
QR_IMG = re.compile(r"(?<!{% if doc.ksa_einv_qr %})(<img\b[^>]*src=\{\{ ?doc\.ksa_einv_qr ?\}\}[^>]*>)")
COMPANY_VAT = "{{ frappe.db.get_value('Company', doc.company, 'tax_id') or '' }}"
MISSING_TEMPLATES = ("Sales Invoice Print",)


def execute():
	repair_letter_heads()
	repair_invoice_formats()
	disable_missing_templates()


def file_missing(url):
	from urllib.parse import unquote

	url = unquote(url.split("?")[0])
	if url.startswith("/files/"):
		return not os.path.exists(frappe.get_site_path("public", "files", url[len("/files/") :]))
	if url.startswith("/private/files/"):
		return not os.path.exists(frappe.get_site_path("private", "files", url[len("/private/files/") :]))
	return False


def without_missing_images(html, header="", footer=""):
	"""Swap the first missing image for `header` and any later ones for `footer`."""
	seen = []

	def swap(match):
		if not file_missing(match.group(1)):
			return match.group(0)
		seen.append(match)
		return header if len(seen) == 1 else footer

	return IMG.sub(swap, html or "")


def company_header(company):
	return f'<div style="text-align:center;font-size:18px;font-weight:bold;">{company}</div>'


def repair_letter_heads():
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	header = company_header(frappe.utils.escape_html(company or ""))
	for lh in frappe.get_all("Letter Head", fields=["name", "content", "footer"]):
		content = without_missing_images(lh.content, header)
		footer = without_missing_images(lh.footer)
		if content != (lh.content or "") or footer != (lh.footer or ""):
			frappe.db.set_value("Letter Head", lh.name, {"content": content, "footer": footer})


def repair_invoice_formats():
	for pf in frappe.get_all(
		"Print Format",
		filters={"doc_type": "Sales Invoice", "standard": "No", "custom_format": 1},
		fields=["name", "html"],
	):
		html = DEAD_ADDRESS_COMMENT.sub("", pf.html or "").replace(OLD_SELLER_VAT, COMPANY_VAT)
		html = without_missing_images(html, company_header("{{ doc.company }}"))
		html = QR_IMG.sub(r"{% if doc.ksa_einv_qr %}\1{% endif %}", html)
		if html != (pf.html or ""):
			frappe.db.set_value("Print Format", pf.name, "html", html)


def disable_missing_templates():
	for name in MISSING_TEMPLATES:
		if frappe.db.get_value("Print Format", name, "disabled") == 0:
			frappe.db.set_value("Print Format", name, "disabled", 1)
