# Copyright (c) 2026, DVNKS Systems and contributors
"""Simran's ONE Freight retest (3 Nov). Runs only on a site that has ONE
FREIGHT SERVICES COMPANY; every other site skips it.

- Item 4: Shipment Type "Saber Registration" goes; it is a service. Where a
  record still uses it, it is disabled instead, so pickers stop offering it.
- Item 8: a new customer's Credit Period defaults to 30 Days.
- Item 9: one sample truck and one sample driver, named as samples, so Start
  transit and Mark Delivered can be tested. Delete both before go-live.
- Clean-up: her second "TEST CUSTOMER (delete)", with the Project made along
  with it (the customer can't go while that Project points to it).
"""

import frappe

from forwarding.patches.v1_0.ofs1_clean_start import COMPANY, remove
from forwarding.patches.v1_0.ofs1_invoice_settings import set_default

SABER = "Saber Registration"
CUSTOMER = "TEST CUSTOMER (delete)"
SAMPLE_PLATE = "SAMPLE-001"
SAMPLE_DRIVER = "SAMPLE DRIVER (delete before go-live)"


def execute():
	if not frappe.db.exists("Company", COMPANY):
		return
	remove("Shipment Type", SABER)
	if frappe.db.exists("Shipment Type", SABER):
		frappe.db.set_value("Shipment Type", SABER, "disabled", 1)
	if frappe.get_meta("Customer").has_field("credit_period"):
		set_default("Customer", "credit_period", "30 Days")
	remove_test_customer()
	add_sample_fleet()


def remove_test_customer():
	for name in frappe.get_all("Customer", filters={"customer_name": CUSTOMER}, pluck="name"):
		# Only a customer nobody has worked with: no job or invoice.
		used = next(
			(dt for dt in ("Operations", "Sales Invoice", "Transportation") if frappe.db.exists(dt, {"customer": name})), None
		)
		if used:
			print(f"Kept Customer {name}: it has a {used}")
			continue
		for project in frappe.get_all("Project", filters={"customer": name}, pluck="name"):
			remove("Project", project)
		remove("Customer", name)


def add_sample_fleet():
	if not frappe.db.exists("Vehicle", SAMPLE_PLATE):
		vehicle = frappe.new_doc("Vehicle")
		vehicle.update({"license_plate": SAMPLE_PLATE, "make": "SAMPLE", "model": "Sample truck - delete before go-live"})
		vehicle.flags.ignore_mandatory = True
		vehicle.insert(ignore_permissions=True)
		print(f"Added Vehicle {vehicle.name}")
	if not frappe.db.exists("Driver", {"full_name": SAMPLE_DRIVER}):
		driver = frappe.new_doc("Driver")
		driver.update({"full_name": SAMPLE_DRIVER, "status": "Active"})
		driver.flags.ignore_mandatory = True
		driver.insert(ignore_permissions=True)
		print(f"Added Driver {driver.name}")
