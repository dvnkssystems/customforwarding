# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Shipping Line and Carrier (airline) records and the Supplier that bills
for them (Phase 2 spec §4).

Shipping Line and Carrier are their own DocTypes, not Suppliers, but purchase
invoices and payments go to a Supplier. Each carries an optional `supplier`
link; setting it ticks the matching role on that supplier, and the supplier's
360 page then lists the jobs that name the line or carrier.
"""

import frappe

# Carrier DocType -> (role tick-box on Supplier, role shown on the supplier's jobs)
ROLES = {
	"Shipping Line": ("is_shipping_line", "Shipping Line"),
	"Carrier": ("is_airline", "Airline"),
}
# Operations field naming each.
JOB_FIELDS = {"Shipping Line": "shipping_line", "Carrier": "carrier"}


def tick_role(supplier, doctype):
	"""Tick the supplier's role for doctype (Shipping Line / Carrier). Written
	directly: the Supplier's own validation (mandatory Tax ID, Branch) is not
	this record's business."""
	field = ROLES[doctype][0]
	if supplier and frappe.db.exists("Supplier", supplier) and not frappe.db.get_value("Supplier", supplier, field):
		frappe.db.set_value("Supplier", supplier, field, 1)


def on_carrier_change(doc, deleted=False):
	from forwarding.job_events import clear_supplier_cache

	before = doc.get_doc_before_save()
	previous = before.get("supplier") if before else None
	if doc.get("supplier") and not deleted:
		tick_role(doc.supplier, doc.doctype)
	clear_supplier_cache(doc.get("supplier"), previous)


def carrier_suppliers(job):
	"""Suppliers linked to the job's Shipping Line and Carrier."""
	out = []
	for doctype, field in JOB_FIELDS.items():
		name = job.get(field) if job else None
		if name:
			out.append(frappe.db.get_value(doctype, name, "supplier"))
	return [s for s in out if s]
