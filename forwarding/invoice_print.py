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
from frappe.utils import cint, cstr, flt, money_in_words

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


def company_header(company_name):
	"""What a bilingual print header shows for a company: logo, names, VAT, CR
	and address in English and Arabic. Anything not filled in on the Company
	comes back empty, so the header simply leaves it out."""
	company = _values(
		"Company",
		company_name,
		["company_name", "company_logo", "tax_id", "tax_number", "cr_number", "company_arabic_name", "address_arabic"],
	)
	address = ""
	if company_name:
		from frappe.contacts.doctype.address.address import get_company_address

		address = _render_address((get_company_address(company_name) or frappe._dict()).get("company_address"))
	return frappe._dict(
		name=company.get("company_name") or company_name or "",
		name_ar=company.get("company_arabic_name") or "",
		logo=_existing_file(company.get("company_logo")),
		tax_id=company.get("tax_id") or company.get("tax_number") or "",
		cr=company.get("cr_number") or "",
		address=address_lines(address),
		address_ar=address_lines(company.get("address_arabic")),
	)


def company_bank(company_name):
	"""The company's default bank account for "pay to" details, or {}.

	The default company Bank Account first, else the first one that is not
	hidden."""
	if not company_name or not frappe.db.exists("DocType", "Bank Account"):
		return frappe._dict()
	meta = frappe.get_meta("Bank Account")
	filters = {"company": company_name, "is_company_account": 1}
	if meta.has_field("disabled"):
		filters["disabled"] = 0
	if meta.has_field("is_hidden"):
		filters["is_hidden"] = 0
	names = frappe.get_all("Bank Account", filters=filters, pluck="name", order_by="is_default desc, creation asc", limit=1)
	if not names:
		return frappe._dict()
	account = _values("Bank Account", names[0], ["bank", "account_name", "bank_account_no", "iban", "swift_code", "branch_code"])
	swift = account.get("swift_code") or (
		frappe.db.get_value("Bank", account.bank, "swift_number") if account.get("bank") else ""
	)
	return frappe._dict(
		bank=account.get("bank") or "",
		account_name=account.get("account_name") or "",
		account_no=account.get("bank_account_no") or "",
		iban=account.get("iban") or "",
		swift=swift or "",
	)


def zatca_qr(doc, seller_name, seller_tax_id):
	"""The invoice's ZATCA QR as an <img> src, or "" (R3-11).

	ksa_compliance is the source wherever it is set up: its Phase 2 record
	(Sales Invoice Additional Fields, made on submit once the company is
	onboarded) first, then its Phase 1 settings. Without either, a Phase 1
	QR -- seller name, VAT number, timestamp, total, VAT -- is built with
	ksa_compliance's own TLV encoder from the seller on the invoice. Only a
	submitted invoice with a seller VAT number gets one: the QR states both.
	Nothing here calls ZATCA.
	"""
	if frappe.db.exists("DocType", "Sales Invoice Additional Fields"):
		siaf = frappe.db.get_value(
			"Sales Invoice Additional Fields",
			{"sales_invoice": doc.name, "docstatus": ["<", 2]},
			"name",
			order_by="creation desc",
		)
		# qr_image_src is worked out by the doc (not a column), as in
		# ksa_compliance's own Phase 2 print format.
		src = siaf and frappe.get_doc("Sales Invoice Additional Fields", siaf).get("qr_image_src")
		if src:
			return src
	legacy = _existing_file(doc.get("ksa_einv_qr"))
	if legacy:
		return legacy
	if doc.docstatus != 1 or not seller_tax_id:
		return ""
	try:
		from ksa_compliance import jinja as ksa
	except ImportError:
		return ""
	try:
		png = ksa.get_zatca_phase_1_qr_for_invoice(doc.name)
		if not png:
			png = ksa._generate_qrcode(
				ksa._generate_decoded_string(
					[
						seller_name,
						seller_tax_id,
						ksa._format_date(doc.posting_date, doc.posting_time or "00:00:00"),
						flt(doc.grand_total, 2),
						flt(doc.total_taxes_and_charges, 2),
					]
				)
			)
	except Exception:
		frappe.log_error(title="ZATCA QR for invoice print", reference_doctype=doc.doctype, reference_name=doc.name)
		return ""
	return f"data:image/png;base64,{png}" if png else ""


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
	customer = _values(
		"Customer", doc.customer, ["tax_id", "custom_vat_registration_number", "customer_name_in_arabic", "cr_no"]
	)
	# The customer form's "VAT Registration Number" is its own field; many
	# customers have only that one (ONE Freight, 2 Nov: buyer VAT printed "-").
	customer_tax_id = (
		doc.get("tax_id") or customer.get("tax_id") or customer.get("custom_vat_registration_number")
	)

	job = frappe._dict()
	if doc.get("operations"):
		job = _values(
			"Operations",
			doc.operations,
			[
				"awb_number", "mbl_number", "house_number", "mode_of_shipment",
				"vessel_name", "voyage_number", "flight_number", "port_of_loading", "port_of_destination",
			],
		)
		if job:
			job["name"] = doc.operations

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

	seller_name = company.get("company_name") or doc.company
	header = company_header(doc.company)
	seller_tax_id = doc.get("company_tax_id") or company.get("tax_id") or header.tax_id or ""
	return frappe._dict(
		seller=frappe._dict(
			name=seller_name,
			name_ar=company.get("company_arabic_name") or "",
			tax_id=seller_tax_id,
			address=address_lines(_company_address(doc)),
			address_ar=address_lines(company.get("address_arabic")),
			logo=header.logo,
			cr=header.cr,
			stamp=company_stamp(doc.company),
		),
		bank=company_bank(doc.company),
		buyer=frappe._dict(
			name=doc.customer_name or doc.customer,
			name_ar=doc.get("customer_name_in_arabic") or customer.get("customer_name_in_arabic") or "",
			tax_id=customer_tax_id or "",
			cr=customer.get("cr_no") or "",
			address=address_lines(doc.get("address_display") or _render_address(doc.get("customer_address"))),
		),
		job_no=job.get("name") or "",
		bl_awb=job.get("awb_number") or job.get("mbl_number") or "",
		hbl=job.get("house_number") or "",
		shipment=invoice_shipment(job),
		lines=lines,
		has_line_vat=bool(vat),
		taxes=[t for t in doc.get("taxes") or [] if flt(t.tax_amount)],
		net_total=doc.net_total,
		discount=doc.get("discount_amount") or 0,
		total_vat=doc.total_taxes_and_charges,
		grand_total=grand_total,
		words_en=doc.get("in_words") or money_in_words(grand_total, doc.currency),
		words_ar=amount_in_words_ar(grand_total, doc.currency),
		qr=zatca_qr(doc, seller_name, seller_tax_id),
		**invoice_title(doc, customer_tax_id),
	)


def company_stamp(company_name):
	"""The Company's stamp image for the print, or "" (ONE Freight, 9 Nov)."""
	if not company_name or not frappe.get_meta("Company").has_field("company_stamp"):
		return ""
	return _existing_file(frappe.db.get_value("Company", company_name, "company_stamp"))


def container_size_type(size, container_type):
	"""A container's size and type as a forwarder writes it: 40' GP.

	The Container Type is often "40GP" (size included) and sometimes only
	"GP" beside the Size column; both read 40' GP."""
	kind = (container_type or "").strip().upper()
	match = re.match(r"^(\d{2})\s*(.*)$", kind)
	if match:
		size, kind = match.group(1), match.group(2)
	size = cstr(size).strip()
	return " ".join(p for p in ((size + "'") if size else "", kind) if p)


# More containers than this print as counts per size/type plus the first
# numbers, so the invoice stays on one page.
MAX_LISTED_CONTAINERS = 40


def invoice_containers(job_name):
	"""The job's containers for the invoice: {"listed": ["MSCU4821356 – 40' GP", ...],
	"more": n, "summary": "35 × 40' GP, 5 × 20' GP"}."""
	if not job_name:
		return frappe._dict(listed=[], more=0, summary="")
	rows = frappe.get_all(
		"Container Details",
		filters={"parent": job_name, "parenttype": "Operations"},
		fields=["container_no", "size", "container_type", "qty"],
		order_by="idx asc",
	)
	listed, counts = [], {}
	for row in rows:
		label = container_size_type(row.size, row.container_type)
		number = (row.container_no or "").strip().upper()
		count = 1 if number else max(cint(row.qty), 1)
		if label:
			counts[label] = counts.get(label, 0) + count
		if number:
			listed.append(f"{number} – {label}" if label else number)
		elif label:
			listed.append(f"{count} × {label}")
	summary = ", ".join(f"{n} × {label}" for label, n in counts.items())
	more = max(len(listed) - MAX_LISTED_CONTAINERS, 0)
	return frappe._dict(listed=listed[:MAX_LISTED_CONTAINERS], more=more, summary=summary if more else "")


def invoice_shipment(job):
	"""Vessel / voyage (or flight), ports and containers for the invoice
	(ONE Freight, 5 and 9 Nov). Empty values are left out by the print."""
	from forwarding.pod_print import port_label

	if not job:
		return frappe._dict()
	is_air = (job.get("mode_of_shipment") or "").strip().lower() == "air"
	carrier = (
		job.get("flight_number")
		if is_air
		else " / ".join(p for p in (job.get("vessel_name"), job.get("voyage_number")) if p)
	)
	return frappe._dict(
		is_air=is_air,
		carrier=carrier or "",
		pol=port_label(job.get("port_of_loading")),
		pod=port_label(job.get("port_of_destination")),
		containers=invoice_containers(job.get("name")),
	)


def invoice_title(doc, buyer_tax_id):
	"""The document's title in English and Arabic, as ZATCA names it.

	A return is a Credit Note and a debit note a Debit Note. Otherwise a buyer
	with a VAT number gets a (standard) Tax Invoice and one without a
	Simplified Tax Invoice.
	"""
	if doc.get("is_return"):
		return {"title": _("Credit Note"), "title_ar": "إشعار دائن"}
	if doc.get("is_debit_note"):
		return {"title": _("Debit Note"), "title_ar": "إشعار مدين"}
	if not buyer_tax_id:
		return {"title": _("Simplified Tax Invoice"), "title_ar": "فاتورة ضريبية مبسطة"}
	return {"title": _("Tax Invoice"), "title_ar": "فاتورة ضريبية"}
