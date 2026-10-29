# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Statement of Account for a Customer or a Supplier (Phase 2 spec CU2 / SU8).

get() returns the statement as data: the balance brought forward, every
voucher booked against the party in the period (invoices, credit / debit
notes, payments, journal entries) with a running balance, the closing
balance, and the ageing of what is still open at the end of the period.
download_pdf() and get_html() render the same statement through
templates/statement_of_account.html, and send_email() mails the PDF.

The ledger is GL Entry (not cancelled) for the party in one company, so the
statement agrees with the General Ledger. Amounts are in that company's
currency. Balances are what the party owes us (Customer: debit - credit) or
what we owe the party (Supplier: credit - debit), so a positive balance is
always money outstanding.

Ageing is worked out from Payment Ledger Entry as of to_date: each invoice's
remaining amount, aged by days past its due date (its posting date if it has
none; not yet due counts as 0-30). Unallocated payments and advances age by
their own date and come off the bucket they fall in.

The company is the one asked for, else the one the party's latest ledger
entry is in, else the site's default company.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Min, Sum
from frappe.utils import cint, date_diff, flt, fmt_money, formatdate, getdate, nowdate

from forwarding.party_360 import default_company, vat_number

# Party type -> the invoice DocType a user must be able to read to see it.
PARTY_TYPES = {"Customer": "Sales Invoice", "Supplier": "Purchase Invoice"}

BUCKETS = (("0-30", 30), ("31-60", 60), ("61-90", 90), ("90+", None))

TEMPLATE = "forwarding/templates/statement_of_account.html"


def _check(party_type, party, ptype="read"):
	if party_type not in PARTY_TYPES:
		frappe.throw(_("Party Type must be Customer or Supplier"))
	if not party or not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} not found").format(_(party_type), party), frappe.DoesNotExistError)
	frappe.has_permission(party_type, ptype, party, throw=True)
	frappe.has_permission(PARTY_TYPES[party_type], "read", throw=True)


@frappe.whitelist()
def get(party_type, party, from_date=None, to_date=None, company=None):
	_check(party_type, party)
	return build(party_type, party, from_date, to_date, company)


@frappe.whitelist()
def get_html(party_type, party, from_date=None, to_date=None, company=None):
	"""{"html": the printable statement}, for an on-screen print view."""
	_check(party_type, party, "print")
	return {"html": render(build(party_type, party, from_date, to_date, company))}


@frappe.whitelist(methods=["GET", "POST"])
def download_pdf(party_type, party, from_date=None, to_date=None, company=None, inline=0):
	"""The statement as a PDF file. inline=1 shows it in the browser (to print)
	instead of downloading it."""
	_check(party_type, party, "print")
	statement = build(party_type, party, from_date, to_date, company)
	frappe.local.response.filename = file_name(statement)
	frappe.local.response.filecontent = pdf(statement)
	frappe.local.response.type = "pdf" if cint(inline) else "download"


@frappe.whitelist(methods=["POST"])
def send_email(
	party_type,
	party,
	recipients=None,
	from_date=None,
	to_date=None,
	company=None,
	subject=None,
	message=None,
	cc=None,
):
	"""Mail the statement PDF. recipients defaults to the party's primary
	contact's email. Returns {"recipients", "subject"}."""
	_check(party_type, party, "email")
	recipients = _split(recipients) or _default_recipients(party_type, party)
	if not recipients:
		frappe.throw(_("No email address to send the statement to. Add one to the primary contact."))

	statement = build(party_type, party, from_date, to_date, company)
	subject = subject or _("Statement of Account: {0} ({1} to {2})").format(
		statement["party_name"], formatdate(statement["from_date"]), formatdate(statement["to_date"])
	)
	message = message or _(
		"Dear {0},<br><br>Please find attached your statement of account for {1} to {2}. "
		"Closing balance: {3}.<br><br>Regards,<br>{4}"
	).format(
		statement["party_name"],
		formatdate(statement["from_date"]),
		formatdate(statement["to_date"]),
		fmt_money(statement["closing_balance"], currency=statement["currency"]),
		statement["company"],
	)
	frappe.sendmail(
		recipients=recipients,
		cc=_split(cc),
		subject=subject,
		message=message,
		attachments=[{"fname": file_name(statement), "fcontent": pdf(statement)}],
		reference_doctype=party_type,
		reference_name=party,
	)
	return {"recipients": recipients, "subject": subject}


# -- Building the statement --------------------------------------------------------


def build(party_type, party, from_date=None, to_date=None, company=None):
	to_date = getdate(to_date or nowdate())
	company = company or _party_company(party_type, party) or default_company()
	from_date = getdate(from_date) if from_date else _fiscal_year_start(company, to_date)
	if from_date > to_date:
		frappe.throw(_("From Date must be on or before To Date"))

	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	# Customer: what they owe us is debit - credit. Supplier: credit - debit.
	sign = 1 if party_type == "Customer" else -1

	gle = frappe.qb.DocType("GL Entry")
	base = (
		(gle.party_type == party_type) & (gle.party == party) & (gle.company == company) & (gle.is_cancelled == 0)
	)
	debit, credit = (
		frappe.qb.from_(gle)
		.select(Sum(gle.debit), Sum(gle.credit))
		.where(base & (gle.posting_date < from_date))
		.run()[0]
	)
	opening = sign * (flt(debit) - flt(credit))

	vouchers = (
		frappe.qb.from_(gle)
		.select(
			gle.posting_date,
			gle.voucher_type,
			gle.voucher_no,
			Sum(gle.debit).as_("debit"),
			Sum(gle.credit).as_("credit"),
			Min(gle.creation).as_("created"),
		)
		.where(base & (gle.posting_date >= from_date) & (gle.posting_date <= to_date))
		.groupby(gle.posting_date, gle.voucher_type, gle.voucher_no)
		.orderby(gle.posting_date)
		.orderby(Min(gle.creation))
		.orderby(gle.voucher_no)
		.run(as_dict=True)
	)
	details = _voucher_details(vouchers, party_type)

	balance = opening
	rows = []
	total_debit = total_credit = 0.0
	for v in vouchers:
		d = details.get((v.voucher_type, v.voucher_no), {})
		amount = sign * (flt(v.debit) - flt(v.credit))
		balance += amount
		total_debit += flt(v.debit)
		total_credit += flt(v.credit)
		rows.append(
			{
				"posting_date": v.posting_date,
				"voucher_type": v.voucher_type,
				"voucher_no": v.voucher_no,
				"type": d.get("type") or _(v.voucher_type),
				"reference": d.get("reference"),
				"operations": d.get("operations"),
				"due_date": d.get("due_date"),
				"debit": flt(v.debit, 2),
				"credit": flt(v.credit, 2),
				"amount": flt(amount, 2),
				"balance": flt(balance, 2),
			}
		)

	party_name = frappe.db.get_value(
		party_type, party, "customer_name" if party_type == "Customer" else "supplier_name"
	)
	statement = {
		"party_type": party_type,
		"party": party,
		"party_name": party_name or party,
		"tax_id": vat_number(frappe.db.get_value(party_type, party, ["tax_id"], as_dict=True) or {}),
		"company": company,
		"currency": currency,
		"from_date": from_date,
		"to_date": to_date,
		"balance_label": _("Receivable") if party_type == "Customer" else _("Payable"),
		"opening_balance": flt(opening, 2),
		"total_debit": flt(total_debit, 2),
		"total_credit": flt(total_credit, 2),
		"closing_balance": flt(balance, 2),
		"rows": rows,
		"ageing": _ageing(party_type, party, company, to_date),
	}
	# Dates and decimals to plain JSON types.
	return frappe.parse_json(frappe.as_json(statement))


def _party_company(party_type, party):
	return frappe.db.get_value(
		"GL Entry",
		{"party_type": party_type, "party": party, "is_cancelled": 0},
		"company",
		order_by="posting_date desc, creation desc",
	)


def _fiscal_year_start(company, day):
	from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

	try:
		return getdate(get_fiscal_year(day, company=company)[1])
	except FiscalYearError:
		return getdate(f"{day.year}-01-01")


def _voucher_details(vouchers, party_type):
	"""{(voucher_type, voucher_no): {type, reference, operations, due_date}}"""
	# Money paid out to a customer, or received back from a supplier.
	refund_type = "Pay" if party_type == "Customer" else "Receive"
	by_type = {}
	for v in vouchers:
		by_type.setdefault(v.voucher_type, []).append(v.voucher_no)

	out = {}
	for doctype, names in by_type.items():
		if doctype in ("Sales Invoice", "Purchase Invoice"):
			fields = ["name", "is_return", "due_date", "operations"]
			if doctype == "Purchase Invoice":
				fields.append("bill_no")
			for r in frappe.get_all(doctype, filters={"name": ["in", names]}, fields=fields):
				if r.is_return:
					kind = _("Credit Note") if doctype == "Sales Invoice" else _("Debit Note")
				else:
					kind = _("Invoice")
				out[(doctype, r.name)] = {
					"type": kind,
					"reference": r.get("bill_no") or r.operations,
					"operations": r.operations,
					"due_date": r.due_date,
				}
		elif doctype == "Payment Entry":
			for r in frappe.get_all(
				doctype, filters={"name": ["in", names]}, fields=["name", "payment_type", "reference_no"]
			):
				out[(doctype, r.name)] = {
					"type": _("Refund") if r.payment_type == refund_type else _("Payment"),
					"reference": r.reference_no,
				}
		elif doctype == "Journal Entry":
			for r in frappe.get_all(
				doctype, filters={"name": ["in", names]}, fields=["name", "cheque_no"]
			):
				out[(doctype, r.name)] = {"type": _("Journal Entry"), "reference": r.cheque_no}
	return out


def _ageing(party_type, party, company, to_date):
	"""{"0-30", "31-60", "61-90", "90+", "total"}: what is open on to_date, by
	days past due."""
	ple = frappe.qb.DocType("Payment Ledger Entry")
	open_items = (
		frappe.qb.from_(ple)
		.select(
			ple.against_voucher_type,
			ple.against_voucher_no,
			Sum(ple.amount).as_("outstanding"),
			Min(ple.posting_date).as_("posting_date"),
		)
		.where(
			(ple.party_type == party_type)
			& (ple.party == party)
			& (ple.company == company)
			& (ple.delinked == 0)
			& (ple.posting_date <= to_date)
		)
		.groupby(ple.against_voucher_type, ple.against_voucher_no)
		.run(as_dict=True)
	)

	due_dates = {}
	for doctype in ("Sales Invoice", "Purchase Invoice"):
		names = [r.against_voucher_no for r in open_items if r.against_voucher_type == doctype]
		if names:
			due_dates.update(
				{
					(doctype, n): d
					for n, d in frappe.get_all(
						doctype, filters={"name": ["in", names]}, fields=["name", "due_date"], as_list=True
					)
				}
			)

	ageing = {label: 0.0 for label, _limit in BUCKETS}
	for r in open_items:
		amount = flt(r.outstanding)
		if abs(amount) < 0.005:
			continue
		since = due_dates.get((r.against_voucher_type, r.against_voucher_no)) or r.posting_date
		days = max(date_diff(to_date, since), 0) if since else 0
		for label, limit in BUCKETS:
			if limit is None or days <= limit:
				ageing[label] += amount
				break
	ageing = {k: flt(v, 2) for k, v in ageing.items()}
	ageing["total"] = flt(sum(ageing.values()), 2)
	return ageing


# -- Rendering ---------------------------------------------------------------------


def render(statement):
	return frappe.render_template(
		TEMPLATE,
		{
			"s": frappe._dict(statement),
			"money": lambda amount: fmt_money(flt(amount), precision=2, currency=statement["currency"]),
			"formatdate": formatdate,
			"buckets": [label for label, _limit in BUCKETS],
			"_": _,
		},
	)


def pdf(statement):
	from frappe.utils.pdf import get_pdf

	return get_pdf(render(statement))


def file_name(statement):
	return "{0} {1} {2} to {3}.pdf".format(
		_("Statement"),
		statement["party"],
		statement["from_date"],
		statement["to_date"],
	).replace("/", "-")


def _split(value):
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("[") else value.replace(";", ",").split(",")
	return [v.strip() for v in value if v and v.strip()]


def _default_recipients(party_type, party):
	link = "customer_primary_contact" if party_type == "Customer" else "supplier_primary_contact"
	contact = frappe.db.get_value(party_type, party, link)
	email = frappe.db.get_value("Contact", contact, "email_id") if contact else None
	if not email:
		email = frappe.db.get_value(party_type, party, "email_id")
	if not email:
		from forwarding.party_360 import CONTACT_FIELDS, linked_party_records

		for c in linked_party_records("Contact", party_type, party, CONTACT_FIELDS, "is_primary_contact", 5):
			if c.email_id:
				email = c.email_id
				break
	return [email] if email else []
