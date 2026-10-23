# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Keep a job's billing status, its Job 360 cache, its customer's
Customer 360 cache and its suppliers' Supplier 360 caches in step with the
documents around them.

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
		# Copies built for a date range (party_360.ranged_cache_key).
		frappe.cache.delete_keys(f"{customer_cache_key(customer)}|")


SUPPLIER_CACHE_PREFIX = "supplier_360:"

# Supplier links on the records Supplier 360 reads. Purchase Invoice is
# `supplier`, Transportation `transporter`, Custom Clearance `broker_name`
# and `transporter_name`; a field a DocType does not have reads as None.
SUPPLIER_FIELDS = ("supplier", "transporter", "broker_name", "transporter_name")
# Operations rows that name a supplier: (table field, link field).
JOB_SUPPLIER_TABLES = (
	("suppliers", "supplier"),
	("transport_container_legs", "transporter"),
	("transport_package_legs", "transporter"),
	("cost_table", "supplier"),
)


def supplier_cache_key(supplier):
	return f"{SUPPLIER_CACHE_PREFIX}{supplier}"


def clear_supplier_cache(*suppliers):
	for supplier in {s for s in suppliers if s}:
		frappe.cache.delete_value(supplier_cache_key(supplier))
		# Copies built for a date range (party_360.ranged_cache_key).
		frappe.cache.delete_keys(f"{supplier_cache_key(supplier)}|")


def job_supplier_links(job):
	"""Suppliers an Operations document names: its handling agent, its
	Suppliers rows, the transporters on its transport legs, the suppliers on
	its cost rows and those linked to its Shipping Line and Carrier."""
	if not job:
		return []
	from forwarding.carriers import carrier_suppliers

	out = [job.get("handling_agent")]
	for table, field in JOB_SUPPLIER_TABLES:
		out += [row.get(field) for row in job.get(table) or []]
	out += carrier_suppliers(job)
	return [s for s in out if s]


def _record_suppliers(doc):
	"""Suppliers a Transportation, Custom Clearance or Purchase Invoice names,
	its cost rows' suppliers included."""
	out = [doc.get(f) for f in SUPPLIER_FIELDS if doc.get(f)]
	out += [row.get("supplier") for row in doc.get("cost_table") or [] if row.get("supplier")]
	return out


def _service_suppliers(*jobs):
	"""Suppliers on the jobs' Transportation and Custom Clearance records."""
	jobs = [j for j in jobs if j]
	if not jobs:
		return []
	out = frappe.get_all(
		"Transportation", filters={"operations": ["in", jobs]}, pluck="transporter"
	)
	for row in frappe.get_all(
		"Custom Clearance",
		filters={"operations": ["in", jobs]},
		fields=["broker_name", "transporter_name"],
	):
		out += [row.broker_name, row.transporter_name]
	return [s for s in out if s]


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
	# Nothing billed is not paid: a zero-value invoice leaves the job Invoiced.
	if total <= TOLERANCE:
		return "Invoiced"
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


def _before(doc):
	return doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None


# -- Operations ---------------------------------------------------------------


def on_job_change(doc, method=None):
	clear_job_cache(doc.name)
	clear_customer_cache(doc.get("customer"), _previous(doc, "customer"))
	# Every supplier the job names, before and after, and those on its
	# services: their pages list the job and count it as active.
	clear_supplier_cache(
		*job_supplier_links(doc), *job_supplier_links(_before(doc)), *_service_suppliers(doc.name)
	)


# -- Transportation, Custom Clearance, Purchase Invoice -------------------------


def on_linked_change(doc, method=None):
	"""A record shown on the job page changed: drop the page's cache, and
	the customer's (their documents tab lists these records' documents)."""
	jobs = (doc.get("operations"), _previous_operations(doc))
	clear_job_cache(*jobs)
	clear_customer_cache(*_job_customers(*jobs))
	before = _before(doc)
	clear_supplier_cache(*_record_suppliers(doc), *(_record_suppliers(before) if before else []))


# -- Sales Invoice ---------------------------------------------------------------


def on_sales_invoice_change(doc, method=None):
	update_billing_status(doc.get("operations"), _previous_operations(doc))
	clear_customer_cache(doc.get("customer"), _previous(doc, "customer"))


# -- Payment Entry / Journal Entry -------------------------------------------------


def clear_payment_party_cache(doc, method=None):
	"""Drop the Customer 360 / Supplier 360 cache of every party a Payment
	Entry or Journal Entry is booked against. Hooked on its own to Payment
	Entry save and delete, since the pages list draft payments too."""
	if doc.doctype == "Payment Entry":
		parties = [(doc.get("party_type"), doc.get("party"))]
	else:
		parties = [(r.party_type, r.party) for r in doc.get("accounts") or []]
	clear_customer_cache(*[p for t, p in parties if t == "Customer"])
	clear_supplier_cache(*[p for t, p in parties if t == "Supplier"])


def on_payment_change(doc, method=None):
	"""Payments change invoice outstanding amounts, so recompute the jobs of
	every Sales Invoice the entry settles, and drop the Customer 360 cache
	of every customer the entry is booked against."""
	clear_payment_party_cache(doc)
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


# -- Customer 360 only ---------------------------------------------------------------


def on_customer_change(doc, method=None):
	clear_customer_cache(doc.name)


def on_quote_change(doc, method=None):
	"""Quote is a custom DocType; its customer is the `consignee` link."""
	clear_customer_cache(doc.get("consignee"), _previous(doc, "consignee"))


def _party_links(doc, party_type):
	return [l.link_name for l in doc.get("links") or [] if l.link_doctype == party_type]


def _customer_links(doc):
	return _party_links(doc, "Customer")


def on_party_detail_change(doc, method=None):
	"""Contact or Address: drop the cache of every customer and supplier it
	is (or was) linked to."""
	before = _before(doc)
	docs = [doc, before] if before else [doc]
	clear_customer_cache(*[c for d in docs for c in _party_links(d, "Customer")])
	clear_supplier_cache(*[s for d in docs for s in _party_links(d, "Supplier")])


def on_file_change(doc, method=None):
	"""Files attached to a Customer or Supplier count as documents on file."""
	if doc.get("attached_to_doctype") == "Customer":
		clear_customer_cache(doc.get("attached_to_name"))
	elif doc.get("attached_to_doctype") == "Supplier":
		clear_supplier_cache(doc.get("attached_to_name"))


# -- Supplier 360 only ---------------------------------------------------------------


def on_supplier_change(doc, method=None):
	clear_supplier_cache(doc.name)


def on_fleet_change(doc, method=None):
	"""Vehicle or Driver: drop the cache of the transporter it belongs to
	(Driver.transporter is ERPNext's; Vehicle.transporter is ours, when set)."""
	before = _before(doc)
	clear_supplier_cache(doc.get("transporter"), before.get("transporter") if before else None)


def on_item_price_change(doc, method=None):
	"""A buying Item Price is one of the supplier's rates (Rates tab, S4)."""
	before = _before(doc)
	suppliers = [doc.get("supplier")] if doc.get("buying") else []
	if before and before.get("buying"):
		suppliers.append(before.get("supplier"))
	clear_supplier_cache(*suppliers)
