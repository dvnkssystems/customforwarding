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

from forwarding import banners, customer_banners, party_360
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
def get(customer, from_date=None, to_date=None):
	"""The page's payload. from_date / to_date (optional, M-18) narrow the job,
	quote, invoice and payment lists and the job and quote counts to that
	range; outstanding, overdue and credit stay as of today."""
	frappe.has_permission("Customer", "read", customer, throw=True)

	date_range = party_360.date_range(from_date, to_date)
	key = party_360.ranged_cache_key(customer_cache_key(customer), date_range)
	payload = frappe.cache.get_value(key)
	if payload is None:
		payload = build(customer, date_range)
		frappe.cache.set_value(key, payload, expires_in_sec=CACHE_SECONDS)

	return _for_user(payload)


def _for_user(payload):
	"""Drop the lists the current user may not read. Works on a copy."""
	return party_360.for_user(payload, "customer", GUARDED)


# -- Building the payload -----------------------------------------------------------


def build(customer, date_range=None):
	doc = frappe.get_doc("Customer", customer)
	today = getdate(nowdate())
	company = default_company()
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None

	contacts = _linked_party_records("Contact", customer, CONTACT_FIELDS, "is_primary_contact")
	addresses = _linked_party_records("Address", customer, ADDRESS_FIELDS, "is_primary_address")

	invoices, receivable = _invoices(customer, company, currency, today, date_range)
	quote_days = customer_banners.quote_expiry_days()
	quotes, quote_counts = _quotes(customer, today, quote_days, date_range)
	documents, documents_on_file, documents_total = _documents(customer)
	credit_limit = _credit_limit(doc, company)
	credit_used = receivable["outstanding"]

	kpis = {
		"active_jobs": _active_job_count(customer, date_range),
		"open_quotes": quote_counts["open"],
		"outstanding": flt(receivable["outstanding"], 2),
		"overdue": flt(receivable["overdue"], 2),
		"credit_used": flt(credit_used, 2),
		"credit_limit": flt(credit_limit, 2),
		"credit_pct": flt(credit_used / credit_limit * 100, 2) if credit_limit else None,
		"documents_on_file": documents_on_file,
		# Every listed document, received or not: the tile reads "1 / 4" as on a job.
		"documents_total": documents_total,
	}

	ctx = {
		"kpis": kpis,
		"currency": currency,
		"overdue": receivable["overdue_rows"],
		"expiring_quotes": quote_counts["expiring"],
		"quote_expiry_days": quote_days,
		"not_invoiced_jobs": _not_invoiced_jobs(customer, today, date_range),
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
			filters={"customer": customer, **party_360.range_filter("date", date_range)},
			fields=JOB_FIELDS,
			order_by="creation desc",
			limit=LIST_LIMIT,
		),
		"quotes": quotes,
		"invoices": invoices,
		"payments": frappe.get_all(
			"Payment Entry",
			filters={
				"party_type": "Customer",
				"party": customer,
				"docstatus": ["<", 2],
				**party_360.range_filter("posting_date", date_range),
			},
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
	salesman = _salesman(doc)
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
		# Empty for the root group ("All Customer Groups"), so the page can
		# hide that pill (CU5).
		"customer_group_parent": (
			frappe.db.get_value("Customer Group", doc.customer_group, "parent_customer_group") or None
		)
		if doc.customer_group
		else None,
		"territory": doc.territory,
		# ERPNext's tax_id, else the VAT number ksa_compliance keeps.
		"tax_id": doc.tax_id or doc.get("custom_vat_registration_number") or None,
		"cr_no": doc.get("cr_no") or None,
		"disabled": doc.disabled,
		"status": status,
		"salesman": salesman,
		# For pre-filling a new job (CU4): Operations.salesman links to Sales
		# Person, so only a salesman that is one; Operations.branch from the
		# Customer's branch.
		"default_salesman": salesman if salesman and frappe.db.exists("Sales Person", salesman) else None,
		"branch": doc.get("branch") or None,
		"credit_limit": flt(credit_limit, 2),
		"primary_contact": party_360.primary_contact(doc.customer_primary_contact, contacts),
		"primary_address": party_360.primary_address(doc.customer_primary_address, addresses),
	}


@frappe.whitelist()
def default_salesperson(customer):
	"""The Sales Person a new job for this customer starts with (M-04): the
	customer's Default Salesperson, else its first Sales Team row, else the
	free-text Sales Person1 when it names a Sales Person. None otherwise."""
	if not customer:
		return None
	frappe.has_permission("Customer", "read", customer, throw=True)
	return customer_default_salesperson(customer)


def customer_default_salesperson(customer):
	"""default_salesperson without the permission check, for server code."""
	if not customer or not frappe.db.exists("Customer", customer):
		return None
	doc = frappe.get_doc("Customer", customer)
	for candidate in _salesman_candidates(doc):
		if frappe.db.exists("Sales Person", candidate):
			return candidate
	return None


def _salesman_candidates(doc):
	if doc.get("default_salesperson"):
		yield doc.default_salesperson
	for row in sorted(doc.get("sales_team") or [], key=lambda r: r.idx):
		if row.sales_person:
			yield row.sales_person
	if cstr(doc.get("sales_person_1")).strip():
		yield doc.sales_person_1.strip()


def _salesman(doc):
	"""Default Salesperson, else the first Sales Team row, else the free-text
	Sales Person1 field, else the salesman on the customer's latest job."""
	for candidate in _salesman_candidates(doc):
		return candidate
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


def _active_job_count(customer, date_range=None):
	ops = frappe.qb.DocType("Operations")
	query = (
		frappe.qb.from_(ops)
		.select(Count(ops.name))
		.where(
			(ops.customer == customer)
			& (ops.docstatus < 2)
			& Coalesce(ops.operations_status, "").notin(INACTIVE_JOB_STATUSES)
		)
	)
	in_range = party_360.range_condition(ops.date, date_range)
	if in_range is not None:
		query = query.where(in_range)
	return query.run()[0][0]


def _invoices(customer, company, currency, today, date_range=None):
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
		for r in party_360.in_range(rows, "posting_date", date_range)[:LIST_LIMIT]
	]
	return listed, {"outstanding": outstanding, "overdue": overdue, "overdue_rows": overdue_rows}


def _not_invoiced_jobs(customer, today, date_range=None):
	"""The customer's jobs raising job banner B5 (delivered or ops completed,
	no invoice): the same check Job 360 makes, banners.not_invoiced."""
	rows = frappe.get_all(
		"Operations",
		filters={"customer": customer, "docstatus": ["<", 2], **party_360.range_filter("date", date_range)},
		fields=["name", "operations_status", "billing_status", "docstatus"],
		order_by="creation desc",
	)
	ctx = {"today": today}
	return [
		{"name": r.name, "operations_status": r.operations_status}
		for r in rows
		if banners.not_invoiced(r, ctx)
	]


def _quotes(customer, today, days=None, date_range=None):
	"""The quote list and the open count, both within date_range (by
	Quote.date) when one is given; quotes about to expire are counted over
	all of them, since that alert is about today."""
	rows = frappe.get_all(
		"Quote",
		filters={"consignee": customer},
		fields=["name", "date", "validity", "mode", "pol", "pod", "total"],
		order_by="date desc, creation desc",
	)
	soon = add_days(today, customer_banners.QUOTE_EXPIRY_DAYS if days is None else days)
	expiring = []
	for r in rows:
		validity = getdate(r.validity) if r.validity else None
		r.status = "Open" if (validity is None or validity >= today) else "Expired"
		if r.status == "Open" and validity and validity <= getdate(soon):
			expiring.append({"name": r.name, "validity": validity})
	rows = party_360.in_range(rows, "date", date_range)
	open_count = sum(1 for r in rows if r.status == "Open")
	return rows[:LIST_LIMIT], {"open": open_count, "expiring": expiring}


def _documents(customer):
	"""Document Table rows of the customer's jobs and their Transportation /
	Custom Clearance records, then the files attached to the Customer.

	Returns (rows, documents_on_file, documents_total) where documents_on_file
	counts every received row and every attached file, beyond the listed rows
	too, and documents_total every row and file, received or not."""
	jobs = frappe.get_all(
		"Operations",
		filters={"customer": customer, "docstatus": ["<", 2]},
		pluck="name",
		order_by="creation desc",
	)
	parents = [("Operations", j) for j in jobs]
	job_of = {("Operations", j): j for j in jobs}
	if jobs:
		for dt in LINKED:
			for linked in frappe.get_all(
				dt,
				filters={"operations": ["in", jobs], "docstatus": ["<", 2]},
				fields=["name", "operations"],
				order_by="creation desc",
			):
				parents.append((dt, linked.name))
				job_of[(dt, linked.name)] = linked.operations

	# Newest job first; the job's own rows, then its linked records'. Copies of
	# one document across a job and its linked records count once.
	rows = party_360.merge_documents(
		party_360.document_rows(parents), lambda r: job_of.get((r["source_doctype"], r["source_name"]))
	)
	file_rows = party_360.attached_file_rows("Customer", customer)

	on_file = sum(r["received"] for r in rows) + len(file_rows)
	total = len(rows) + len(file_rows)
	# Customer files first: they are about the customer, not one shipment.
	return (file_rows + rows)[:DOCUMENT_LIMIT], on_file, total
