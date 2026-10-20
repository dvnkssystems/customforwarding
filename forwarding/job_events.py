# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Keep a job's billing status, its Job 360 cache and its customer's
Customer 360 cache in step with the documents around them.

Wired up in hooks.py doc_events. Billing status is written with
frappe.db.set_value rather than a save, so it also works on submitted jobs
and does not re-run the job's validation.
"""

import frappe
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt

CACHE_PREFIX = "job_360:"

# Amounts closer than this count as equal (currency precision is 2 places).
TOLERANCE = 0.005


def cache_key(job):
	return f"{CACHE_PREFIX}{job}"


# The worklist spans many jobs, so instead of tracking which cached lists a
# job appears in, any job change moves this version on and every cached
# worklist (keyed by it) is simply never read again; they expire in 60 s.
WORKLIST_VERSION_KEY = "job_360_worklist_version"


def worklist_version():
	return frappe.cache.get_value(WORKLIST_VERSION_KEY) or "0"


def bump_worklist_version():
	frappe.cache.set_value(WORKLIST_VERSION_KEY, frappe.generate_hash(length=10))


def clear_job_cache(*jobs):
	cleared = False
	for job in jobs:
		if job:
			frappe.cache.delete_value(cache_key(job))
			cleared = True
	if cleared:
		bump_worklist_version()


CUSTOMER_CACHE_PREFIX = "customer_360:"


def customer_cache_key(customer):
	return f"{CUSTOMER_CACHE_PREFIX}{customer}"


def clear_customer_cache(*customers):
	for customer in {c for c in customers if c}:
		frappe.cache.delete_value(customer_cache_key(customer))


def _job_customers(*jobs):
	jobs = [j for j in jobs if j]
	if not jobs:
		return []
	return frappe.get_all("Operations", filters={"name": ["in", jobs]}, pluck="customer")


def get_billing_status(job):
	"""No Invoice, Invoiced, Partly Paid or Paid, from the job's submitted
	Sales Invoices. Credit notes are left out: they already reduce the
	outstanding amount of the invoice they return against."""
	si = frappe.qb.DocType("Sales Invoice")
	count, total, outstanding = (
		frappe.qb.from_(si)
		.select(Count(si.name), Sum(si.grand_total), Sum(si.outstanding_amount))
		.where((si.operations == job) & (si.docstatus == 1) & (si.is_return == 0))
		.run()[0]
	)
	if not count:
		return "No Invoice"

	total, outstanding = flt(total), flt(outstanding)
	if outstanding <= TOLERANCE:
		return "Paid"
	if outstanding >= total - TOLERANCE:
		return "Invoiced"
	return "Partly Paid"


def update_billing_status(*jobs):
	for job in {j for j in jobs if j}:
		status = get_billing_status(job)
		if frappe.db.get_value("Operations", job, "billing_status") != status:
			frappe.db.set_value("Operations", job, "billing_status", status, update_modified=False)
		clear_job_cache(job)


def _previous(doc, fieldname):
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	return before.get(fieldname) if before else None


def _previous_operations(doc):
	return _previous(doc, "operations")


# -- Operations ---------------------------------------------------------------


def on_job_change(doc, method=None):
	clear_job_cache(doc.name)
	clear_customer_cache(doc.get("customer"), _previous(doc, "customer"))


# -- Transportation, Custom Clearance, Purchase Invoice -------------------------


def on_linked_change(doc, method=None):
	"""A record shown on the job page changed: drop the page's cache, and
	the customer's (their documents tab lists these records' documents)."""
	jobs = (doc.get("operations"), _previous_operations(doc))
	clear_job_cache(*jobs)
	clear_customer_cache(*_job_customers(*jobs))


# -- Sales Invoice ---------------------------------------------------------------


def on_sales_invoice_change(doc, method=None):
	update_billing_status(doc.get("operations"), _previous_operations(doc))
	clear_customer_cache(doc.get("customer"), _previous(doc, "customer"))


# -- Payment Entry / Journal Entry -------------------------------------------------


def on_payment_change(doc, method=None):
	"""Payments change invoice outstanding amounts, so recompute the jobs of
	every Sales Invoice the entry settles, and drop the Customer 360 cache
	of every customer the entry is booked against."""
	if doc.doctype == "Payment Entry":
		if doc.get("party_type") == "Customer":
			clear_customer_cache(doc.get("party"))
		invoices = [
			r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Sales Invoice"
		]
	else:
		clear_customer_cache(
			*[r.party for r in doc.get("accounts") or [] if r.party_type == "Customer"]
		)
		invoices = [
			r.reference_name for r in doc.get("accounts") or [] if r.reference_type == "Sales Invoice"
		]
	if not invoices:
		return

	jobs = frappe.get_all(
		"Sales Invoice",
		filters={"name": ["in", list(set(invoices))], "operations": ["is", "set"]},
		pluck="operations",
	)
	update_billing_status(*jobs)


# -- Customer 360 only ---------------------------------------------------------------


def on_customer_change(doc, method=None):
	clear_customer_cache(doc.name)


def on_quote_change(doc, method=None):
	"""Quote is a custom DocType; its customer is the `consignee` link."""
	clear_customer_cache(doc.get("consignee"), _previous(doc, "consignee"))


def _customer_links(doc):
	return [l.link_name for l in doc.get("links") or [] if l.link_doctype == "Customer"]


def on_party_detail_change(doc, method=None):
	"""Contact or Address: drop the cache of every customer it is (or was)
	linked to."""
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	clear_customer_cache(*_customer_links(doc), *(_customer_links(before) if before else []))


def on_file_change(doc, method=None):
	"""Files attached to a Customer count as documents on file."""
	if doc.get("attached_to_doctype") == "Customer":
		clear_customer_cache(doc.get("attached_to_name"))
