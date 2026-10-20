# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Customer 360: everything about one customer in a single call.

get() reads the Customer and the records around it -- jobs (Operations),
quotes (Quote, whose customer is `consignee`), Sales Invoices, Payment
Entries, the documents on the customer's jobs and on the Customer itself,
Contacts and Addresses -- and folds them into KPIs, banners and lists.

Money is in the company currency of the site's default company, and only that
company's invoices count towards outstanding and credit used.

The payload is cached for 60 seconds per customer under customer_360:{customer};
the hooks in forwarding.job_events drop it whenever one of those records
changes. Read permission on the Customer is the gate. Since the cache is
shared between users, each list is then removed for anyone without read
access to its DocType.
"""

import json

import frappe
from frappe.query_builder.functions import Coalesce, Count
from frappe.utils import add_days, cstr, flt, getdate, nowdate

from forwarding import customer_banners, party_360
from forwarding.job_events import customer_cache_key
from forwarding.party_360 import ADDRESS_FIELDS, CONTACT_FIELDS, default_company

CACHE_SECONDS = 60
# Rows per list. The KPIs are counted over everything, not just these rows.
LIST_LIMIT = 100
DOCUMENT_LIMIT = 200

INACTIVE_JOB_STATUSES = ("Closed", "Cancelled")
# Linked records whose Document Table rows count as the job's documents
# (same set Job 360 merges).
LINKED = ("Transportation", "Custom Clearance")

# List in the payload -> DocType a user must be able to read to see it.
GUARDED = {
	"jobs": "Operations",
	"quotes": "Quote",
	"invoices": "Sales Invoice",
	"payments": "Payment Entry",
	"documents": "Operations",
	"contacts": "Contact",
	"addresses": "Address",
}

JOB_FIELDS = [
	"name",
	"operations_status",
	"billing_status",
	"mode_of_shipment",
	"job_type",
	"port_of_loading",
	"port_of_destination",
	"etd_date",
	"eta_date",
	"date",
	"docstatus",
]
PAYMENT_FIELDS = [
	"name",
	"posting_date",
	"paid_amount",
	"payment_type",
	"mode_of_payment",
	"docstatus",
	"reference_no",
]

@frappe.whitelist(methods=["GET"])
def get(customer):
	frappe.has_permission("Customer", "read", customer, throw=True)

	payload = frappe.cache.get_value(customer_cache_key(customer))
	if payload is None:
		payload = build(customer)
		frappe.cache.set_value(customer_cache_key(customer), payload, expires_in_sec=CACHE_SECONDS)

	return _for_user(payload)


def _for_user(payload):
	"""Drop the lists the current user may not read. Works on a copy."""
	return party_360.for_user(payload, "customer", GUARDED)


# -- Building the payload -----------------------------------------------------------


def build(customer):
	doc = frappe.get_doc("Customer", customer)
	today = getdate(nowdate())
	company = default_company()
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None

	contacts = _linked_party_records("Contact", customer, CONTACT_FIELDS, "is_primary_contact")
	addresses = _linked_party_records("Address", customer, ADDRESS_FIELDS, "is_primary_address")

	invoices, receivable = _invoices(customer, company, currency, today)
	quotes, quote_counts = _quotes(customer, today)
	documents, documents_on_file = _documents(customer)
	credit_limit = _credit_limit(doc, company)
	credit_used = receivable["outstanding"]

	kpis = {
		"active_jobs": _active_job_count(customer),
		"open_quotes": quote_counts["open"],
		"outstanding": flt(receivable["outstanding"], 2),
		"overdue": flt(receivable["overdue"], 2),
		"credit_used": flt(credit_used, 2),
		"credit_limit": flt(credit_limit, 2),
		"credit_pct": flt(credit_used / credit_limit * 100, 2) if credit_limit else None,
		"documents_on_file": documents_on_file,
	}

	ctx = {
		"kpis": kpis,
		"currency": currency,
		"overdue": receivable["overdue_rows"],
		"expiring_quotes": quote_counts["expiring"],
		"today": today,
	}

	payload = {
		# Every money KPI and banner amount is in this, the company's currency.
		"currency": currency,
		"customer": _customer_header(doc, company, credit_limit, contacts, addresses),
		"kpis": kpis,
		"banners": customer_banners.evaluate(ctx),
		"jobs": frappe.get_all(
			"Operations",
			filters={"customer": customer},
			fields=JOB_FIELDS,
			order_by="creation desc",
			limit=LIST_LIMIT,
		),
		"quotes": quotes,
		"invoices": invoices,
		"payments": frappe.get_all(
			"Payment Entry",
			filters={"party_type": "Customer", "party": customer, "docstatus": ["<", 2]},
			fields=PAYMENT_FIELDS,
			order_by="posting_date desc, creation desc",
			limit=LIST_LIMIT,
		),
		"documents": documents,
		"contacts": contacts,
		"addresses": addresses,
	}
	# Dates and decimals to plain JSON types, so the cached copy and the
	# response are the same thing.
	return json.loads(frappe.as_json(payload))


def _customer_header(doc, company, credit_limit, contacts, addresses):
	if doc.disabled:
		status = "Disabled"
	elif doc.get("is_blocked") or doc.get("is_frozen"):
		status = "Blocked"
	else:
		status = "Active"

	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"customer_group": doc.customer_group,
		"territory": doc.territory,
		# ERPNext's tax_id, else the VAT number ksa_compliance keeps.
		"tax_id": doc.tax_id or doc.get("custom_vat_registration_number") or None,
		"cr_no": doc.get("cr_no") or None,
		"disabled": doc.disabled,
		"status": status,
		"salesman": _salesman(doc),
		"credit_limit": flt(credit_limit, 2),
		"primary_contact": party_360.primary_contact(doc.customer_primary_contact, contacts),
		"primary_address": party_360.primary_address(doc.customer_primary_address, addresses),
	}


def _salesman(doc):
	"""First Sales Team row, else the free-text Sales Person1 field, else
	the salesman on the customer's latest job."""
	for row in sorted(doc.get("sales_team") or [], key=lambda r: r.idx):
		if row.sales_person:
			return row.sales_person
	if cstr(doc.get("sales_person_1")).strip():
		return doc.sales_person_1.strip()
	return frappe.db.get_value(
		"Operations",
		{"customer": doc.name, "salesman": ["is", "set"], "docstatus": ["<", 2]},
		"salesman",
		order_by="creation desc",
	)


def _credit_limit(doc, company):
	"""ERPNext's Customer Credit Limit row for the company, else the
	Freight Settings credit limit (credit_limit_flcs)."""
	for row in doc.get("credit_limits") or []:
		if row.company == company and flt(row.credit_limit):
			return flt(row.credit_limit)
	return flt(doc.get("credit_limit_flcs"))


def _linked_party_records(doctype, customer, fields, primary_field):
	"""Contacts or Addresses linked to the customer, primary first."""
	return party_360.linked_party_records(doctype, "Customer", customer, fields, primary_field, LIST_LIMIT)


def _active_job_count(customer):
	ops = frappe.qb.DocType("Operations")
	return (
		frappe.qb.from_(ops)
		.select(Count(ops.name))
		.where(
			(ops.customer == customer)
			& (ops.docstatus < 2)
			& Coalesce(ops.operations_status, "").notin(INACTIVE_JOB_STATUSES)
		)
		.run()[0][0]
	)


def _invoices(customer, company, currency, today):
	"""The invoice list, and the receivable totals in company currency.

	Outstanding is over every submitted invoice of the company (credit notes
	included, their negative outstanding nets off), not just the listed rows.
	"""
	si = frappe.qb.DocType("Sales Invoice")
	rows = (
		frappe.qb.from_(si)
		.select(
			si.name,
			si.posting_date,
			si.due_date,
			si.grand_total,
			si.outstanding_amount,
			si.status,
			si.docstatus,
			si.operations,
			si.company,
			si.party_account_currency,
			si.conversion_rate,
		)
		.where((si.customer == customer) & (si.docstatus < 2))
		.orderby(si.posting_date, order=frappe.qb.desc)
		.orderby(si.creation, order=frappe.qb.desc)
		.run(as_dict=True)
	)

	def base_outstanding(r):
		return party_360.base_outstanding(r, currency)

	def is_overdue(r):
		return party_360.is_overdue(r, today)

	outstanding = overdue = 0.0
	overdue_rows = []
	for r in rows:
		if r.docstatus != 1 or r.company != company:
			continue
		amount = base_outstanding(r)
		outstanding += amount
		if is_overdue(r):
			overdue += amount
			overdue_rows.append({"name": r.name, "due_date": getdate(r.due_date), "outstanding": amount})

	listed = [
		{
			"name": r.name,
			"posting_date": r.posting_date,
			"due_date": r.due_date,
			"grand_total": r.grand_total,
			"outstanding_amount": r.outstanding_amount,
			"status": r.status,
			"docstatus": r.docstatus,
			"operations": r.operations,
			"overdue": is_overdue(r),
		}
		for r in rows[:LIST_LIMIT]
	]
	return listed, {"outstanding": outstanding, "overdue": overdue, "overdue_rows": overdue_rows}


def _quotes(customer, today):
	rows = frappe.get_all(
		"Quote",
		filters={"consignee": customer},
		fields=["name", "date", "validity", "mode", "pol", "pod", "total"],
		order_by="date desc, creation desc",
	)
	soon = add_days(today, customer_banners.QUOTE_EXPIRY_DAYS)
	open_count = 0
	expiring = []
	for r in rows:
		validity = getdate(r.validity) if r.validity else None
		r.status = "Open" if (validity is None or validity >= today) else "Expired"
		if r.status == "Open":
			open_count += 1
			if validity and validity <= getdate(soon):
				expiring.append({"name": r.name, "validity": validity})
	return rows[:LIST_LIMIT], {"open": open_count, "expiring": expiring}


def _documents(customer):
	"""Document Table rows of the customer's jobs and their Transportation /
	Custom Clearance records, then the files attached to the Customer.

	Returns (rows, documents_on_file) where documents_on_file counts every
	received row and every attached file, beyond the listed rows too."""
	jobs = frappe.get_all(
		"Operations",
		filters={"customer": customer, "docstatus": ["<", 2]},
		pluck="name",
		order_by="creation desc",
	)
	parents = [("Operations", j) for j in jobs]
	if jobs:
		for dt in LINKED:
			parents += [
				(dt, n)
				for n in frappe.get_all(
					dt,
					filters={"operations": ["in", jobs], "docstatus": ["<", 2]},
					pluck="name",
					order_by="creation desc",
				)
			]

	# Newest job first; the job's own rows, then its linked records'.
	rows = party_360.document_rows(parents)
	file_rows = party_360.attached_file_rows("Customer", customer)

	on_file = sum(r["received"] for r in rows) + len(file_rows)
	# Customer files first: they are about the customer, not one shipment.
	return (file_rows + rows)[:DOCUMENT_LIMIT], on_file
