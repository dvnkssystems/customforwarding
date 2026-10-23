# Copyright (c) 2026, DVNKS Systems and contributors
"""Data for the "Freight Tax Invoice" print format.

The print format only lays things out; everything it shows is worked out
here so it can be tested: seller and buyer with their VAT numbers, the job
and its BL/AWB, per-line VAT, and the amount in words in English and Arabic.

Addresses come from the text stored on the invoice (address_display and
company_address_display), as they were when it was made. Lines that are just
"None" are dropped: an Address Template that printed an empty field without a
guard wrote that text into invoices that are already submitted, and those are
not rewritten (see patches/v1_0/fix_address_template_none.py).
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, flt, money_in_words

LINE_BREAK = re.compile(r"<br\s*/?>|\n", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
EMPTY_PARTS = {"", "none", "null"}

# Currency names for the Arabic amount in words. Anything else falls back
# to the currency code.
ARABIC_CURRENCY = {
	"SAR": ("ريال سعودي", "هللة"),
	"USD": ("دولار أمريكي", "سنت"),
	"EUR": ("يورو", "سنت"),
	"AED": ("درهم إماراتي", "فلس"),
	"GBP": ("جنيه إسترليني", "بنس"),
	"INR": ("روبية هندية", "بيسة"),
	"KWD": ("دينار كويتي", "فلس"),
	"BHD": ("دينار بحريني", "فلس"),
	"QAR": ("ريال قطري", "درهم"),
	"OMR": ("ريال عماني", "بيسة"),
	"EGP": ("جنيه مصري", "قرش"),
	"CNY": ("يوان صيني", "فين"),
}


def address_lines(html):
	"""Stored address HTML as a list of non-empty lines, "None" parts dropped."""
	lines = []
	for raw in LINE_BREAK.split(html or ""):
		text = TAG.sub("", raw).strip().strip(",").strip()
		if text.lower() in EMPTY_PARTS:
			continue
		# "Surat, None" -> "Surat": a None between commas on one line.
		parts = [p.strip() for p in text.split(",")]
		text = ", ".join(p for p in parts if p.lower() not in EMPTY_PARTS)
		if text:
			lines.append(text)
	return lines


def _values(doctype, name, fields):
	"""The fields this site has, as a dict; missing custom fields are skipped."""
	if not name:
		return frappe._dict()
	meta = frappe.get_meta(doctype)
	fields = [f for f in fields if meta.has_field(f)]
	return frappe.db.get_value(doctype, name, fields, as_dict=True) or frappe._dict()


def _existing_file(url):
	"""`url` when it is a site file that is on disk (or not a site file), else "".

	wkhtmltopdf refuses the whole PDF over one broken <img>.
	"""
	if not url:
		return ""
	from forwarding.patches.v1_0.repair_print_formats import file_missing

	return "" if file_missing(url) else url


def _render_address(name):
	if not name:
		return ""
	from frappe.contacts.doctype.address.address import get_address_display

	try:
		return get_address_display(name) or ""
	except Exception:
		return ""


def _company_address(doc):
	if doc.get("company_address_display"):
		return doc.company_address_display
	name = doc.get("company_address")
	if not name:
		from frappe.contacts.doctype.address.address import get_company_address

		name = (get_company_address(doc.company) or frappe._dict()).get("company_address")
	return _render_address(name)


def amount_in_words_ar(amount, currency):
	"""Arabic amount in words, or "" when num2words cannot do it."""
	try:
		from num2words import num2words
	except ImportError:
		return ""

	amount = abs(flt(amount))
	fraction_units = cint(frappe.db.get_value("Currency", currency, "fraction_units")) or 100
	whole = int(amount)
	fraction = int(round((amount - whole) * fraction_units))
	if fraction >= fraction_units:
		whole, fraction = whole + 1, 0
	main, sub = ARABIC_CURRENCY.get(currency, (currency, ""))
	try:
		words = f"{num2words(whole, lang='ar')} {main}"
		if fraction:
			words += f" و{num2words(fraction, lang='ar')} {sub or ''}".rstrip()
	except Exception:
		return ""
	return f"{words} فقط لا غير"


def _line_vat(doc):
	"""{item row name: (vat rate, vat amount in invoice currency)}."""
	conversion = flt(doc.get("conversion_rate")) or 1
	vat = {}
	details = doc.get("item_wise_tax_details") or []
	if details:
		for d in details:
			rate, amount = vat.get(d.item_row, (0.0, 0.0))
			vat[d.item_row] = (rate + flt(d.rate), amount + flt(d.amount) / conversion)
		return vat

	# Older invoices without the detail table: taxes on net total, with the
	# item's own rate where it has one.
	on_net = [t for t in doc.get("taxes") or [] if t.charge_type == "On Net Total"]
	if not on_net:
		return vat
	for item in doc.get("items") or []:
		try:
			item_rates = json.loads(item.item_tax_rate or "{}") or {}
		except ValueError:
			item_rates = {}
		rate = sum(flt(item_rates.get(t.account_head, t.rate)) for t in on_net)
		vat[item.name] = (rate, flt(item.net_amount) * rate / 100)
	return vat


def get_tax_invoice_context(doc):
	"""Everything the Freight Tax Invoice print format shows."""
	company = _values("Company", doc.company, ["company_name", "tax_id", "company_arabic_name", "address_arabic"])
	customer = _values("Customer", doc.customer, ["tax_id", "customer_name_in_arabic"])
	customer_tax_id = doc.get("tax_id") or customer.get("tax_id")

	job = frappe._dict()
	if doc.get("operations"):
		job = frappe.db.get_value(
			"Operations",
			doc.operations,
			["name", "awb_number", "mbl_number", "house_number"],
			as_dict=True,
		) or frappe._dict()

	precision = doc.precision("amount", "items") if doc.get("items") else 2
	vat = _line_vat(doc)
	lines = []
	for item in doc.get("items") or []:
		rate, amount = vat.get(item.name, (None, None))
		lines.append(
			frappe._dict(
				idx=item.idx,
				description=item.item_name or item.item_code,
				detail=item.description if item.description and item.description != item.item_name else "",
				qty="%g" % flt(item.qty, 3),
				uom=item.uom,
				rate=item.rate,
				amount=item.amount,
				vat_rate=("%g" % flt(rate, 2)) if rate is not None else None,
				vat_amount=flt(amount, precision) if amount is not None else None,
				total=flt(item.net_amount + (amount or 0), precision),
			)
		)

	grand_total = doc.rounded_total if doc.get("rounded_total") and not doc.get("disable_rounded_total") else doc.grand_total

	return frappe._dict(
		seller=frappe._dict(
			name=company.get("company_name") or doc.company,
			name_ar=company.get("company_arabic_name") or "",
			tax_id=doc.get("company_tax_id") or company.get("tax_id") or "",
			address=address_lines(_company_address(doc)),
			address_ar=address_lines(company.get("address_arabic")),
		),
		buyer=frappe._dict(
			name=doc.customer_name or doc.customer,
			name_ar=doc.get("customer_name_in_arabic") or customer.get("customer_name_in_arabic") or "",
			tax_id=customer_tax_id or "",
			address=address_lines(doc.get("address_display") or _render_address(doc.get("customer_address"))),
		),
		job_no=job.get("name") or "",
		bl_awb=job.get("awb_number") or job.get("mbl_number") or "",
		hbl=job.get("house_number") or "",
		lines=lines,
		has_line_vat=bool(vat),
		taxes=[t for t in doc.get("taxes") or [] if flt(t.tax_amount)],
		net_total=doc.net_total,
		discount=doc.get("discount_amount") or 0,
		total_vat=doc.total_taxes_and_charges,
		grand_total=grand_total,
		words_en=doc.get("in_words") or money_in_words(grand_total, doc.currency),
		words_ar=amount_in_words_ar(grand_total, doc.currency),
		qr=_existing_file(doc.get("ksa_einv_qr")),
		title=_("Tax Invoice") if not doc.get("is_return") else _("Credit Note"),
		title_ar="فاتورة ضريبية" if not doc.get("is_return") else "إشعار دائن",
	)
