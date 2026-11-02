# Copyright (c) 2026, DVNKS Systems and contributors
"""A clean start for ONE FREIGHT SERVICES COMPANY (Simran, 2 Nov). Runs only
on a site that has that company; every other site skips it.

- Simran's test records go, so the client starts clean: invoice JSI-26-0001
  (cancelled first; its ledger entries removed), Transportation TJIS2600001,
  job J-IM-S-26-00001 (cancelled first) and customer "TEST CUSTOMER (delete)".
  A series whose last number was one of these (the invoice's, the
  customer's code) steps back, so the client's first invoice is 0001 again.
- Item 4: Shipment Types EER REGISTRATION, IECEE registration and LAB TEST
  go; they are services, not shipment types.

Each record is removed only if it is still there, and a record something
else now uses is left and reported, not forced.
"""

import re

import frappe

COMPANY = "ONE FREIGHT SERVICES COMPANY"
# In order: what links to a record goes before it.
TEST_RECORDS = [
	("Sales Invoice", "JSI-26-0001"),
	("Transportation", "TJIS2600001"),
	("Operations", "J-IM-S-26-00001"),
	("Customer", "TEST CUSTOMER (delete)"),
]
NOT_SHIPMENT_TYPES = ["EER REGISTRATION", "IECEE registration", "LAB TEST"]
LEDGERS = ("GL Entry", "Payment Ledger Entry")


def execute():
	if not frappe.db.exists("Company", COMPANY):
		return
	for doctype, name in TEST_RECORDS:
		remove(doctype, name)
	for name in NOT_SHIPMENT_TYPES:
		remove("Shipment Type", name)


def remove(doctype, name):
	if not frappe.db.exists(doctype, name):
		return
	try:
		with savepoint():
			doc = frappe.get_doc(doctype, name)
			code = doc.get("customer_code")
			if doc.meta.is_submittable and doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
			for ledger in LEDGERS:
				if frappe.db.table_exists(ledger):
					frappe.db.delete(ledger, {"voucher_type": doctype, "voucher_no": name})
			frappe.delete_doc(doctype, name, ignore_permissions=True)
			step_back_series(name)
			if code:
				step_back_series(code)
			print(f"Removed {doctype} {name}")
	except Exception as e:
		print(f"Kept {doctype} {name}: {e}")


class savepoint:
	"""Roll one record's removal back on its own when it fails."""

	def __enter__(self):
		frappe.db.savepoint("ofs1_clean_start")

	def __exit__(self, kind, value, traceback):
		if kind:
			frappe.db.rollback(save_point="ofs1_clean_start")
		return False


def step_back_series(name):
	"""JSI-26-0001 was the series' last number: set JSI-26- back to 0."""
	match = re.match(r"^(.*?)(\d+)$", name)
	if not match:
		return
	prefix, number = match.group(1), int(match.group(2))
	current = frappe.db.sql("select current from `tabSeries` where name = %s", prefix)
	if current and current[0][0] == number:
		frappe.db.sql("update `tabSeries` set current = %s where name = %s", (number - 1, prefix))
