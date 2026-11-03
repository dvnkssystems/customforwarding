# Copyright (c) 2026, DVNKS Systems and contributors
"""Simran's ONE Freight retest (3 Nov, second round). Runs only on a site that
has ONE FREIGHT SERVICES COMPANY; every other site skips it.

- Clean-up: every record of her test customer "TEST CUSTOMER (delete)" goes:
  its invoices, transports, jobs (cancelled first), the Projects made with
  the jobs, then the customer.
- Job numbering back to 0001. A job's name is format
  {branch}-{type}-{mode}-{YY}-{#####}: its counter is the series row named ""
  (blank), shared by every DocType numbered that way, not "J-IM-S-26-". It is
  set back to the highest number a remaining record of those DocTypes carries,
  so no number can come round twice. A transport is named from its job (TT-{operations}), so it
  follows. The customer's and invoice's series step back with their records.
- Item 5: port "Jeddah islamic port" is "Jeddah Islamic Port", the record
  renamed with it (SAJED-Jeddah Islamic Port), links following.
"""

import re

import frappe

from forwarding.patches.v1_0.ofs1_clean_start import COMPANY, remove

CUSTOMER = "TEST CUSTOMER (delete)"
# What links to a job or customer goes before it.
BY_CUSTOMER = ["Sales Invoice", "Transportation", "Operations", "Project"]
PORT_FROM = "SAJED-Jeddah islamic port"
PORT_NAME = "Jeddah Islamic Port"


def execute():
	if not frappe.db.exists("Company", COMPANY):
		return
	remove_test_records()
	reset_job_counter()
	fix_port()


def remove_test_records():
	for customer in frappe.get_all("Customer", filters={"customer_name": CUSTOMER}, pluck="name"):
		for doctype in BY_CUSTOMER:
			for name in frappe.get_all(doctype, filters={"customer": customer}, pluck="name", order_by="creation desc"):
				remove(doctype, name)
		remove("Customer", customer)


def counted_by_blank_series():
	"""{DocType: digits} for DocTypes named format:…{#…}. Frappe numbers each
	braced part on its own, so all of them share the blank series row."""
	out = {}
	for row in frappe.get_all("DocType", filters={"autoname": ["like", "format:%{#%"]}, fields=["name", "autoname"]):
		hashes = re.findall(r"\{(#+)\}", row.autoname)
		if hashes and frappe.db.table_exists(row.name):
			out[row.name] = len(hashes[-1])
	return out


def reset_job_counter():
	"""The blank counter down to the highest number a record still carries
	(0 once the test jobs are gone and nothing else uses it), never lower."""
	highest = 0
	for doctype, digits in counted_by_blank_series().items():
		for name in frappe.get_all(doctype, pluck="name"):
			tail = str(name)[-digits:]
			if tail.isdigit():
				highest = max(highest, int(tail))
	current = frappe.db.sql("select current from `tabSeries` where name = ''")
	if current and current[0][0] > highest:
		frappe.db.sql("update `tabSeries` set current = %s where name = ''", highest)
		print(f"Job numbering: next job is {highest + 1:05d}")


def fix_port():
	if not frappe.db.exists("Port", PORT_FROM):
		return
	code = frappe.db.get_value("Port", PORT_FROM, "port_code")
	target = f"{code}-{PORT_NAME}"
	# The database matches names regardless of case: through a temporary name.
	temporary = f"{target} (renaming)"
	frappe.rename_doc("Port", PORT_FROM, temporary, force=True, show_alert=False)
	frappe.rename_doc("Port", temporary, target, force=True, show_alert=False)
	frappe.db.set_value("Port", target, "port_name", PORT_NAME)
	print(f"Port {PORT_FROM} is now {target}")
