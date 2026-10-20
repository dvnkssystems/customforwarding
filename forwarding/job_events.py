# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Keep a job's billing status and its Job 360 cache in step with the
documents around it.

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


def _previous_operations(doc):
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	return before.get("operations") if before else None


# -- Operations ---------------------------------------------------------------


def on_job_change(doc, method=None):
	clear_job_cache(doc.name)


# -- Transportation, Custom Clearance, Purchase Invoice -------------------------


def on_linked_change(doc, method=None):
	"""A record shown on the job page changed: drop the page's cache."""
	clear_job_cache(doc.get("operations"), _previous_operations(doc))


# -- Sales Invoice ---------------------------------------------------------------


def on_sales_invoice_change(doc, method=None):
	update_billing_status(doc.get("operations"), _previous_operations(doc))


# -- Payment Entry / Journal Entry -------------------------------------------------


def on_payment_change(doc, method=None):
	"""Payments change invoice outstanding amounts, so recompute the jobs of
	every Sales Invoice the entry settles."""
	if doc.doctype == "Payment Entry":
		invoices = [
			r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Sales Invoice"
		]
	else:
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
