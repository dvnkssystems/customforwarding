# Copyright (c) 2026, DVNKS Systems and contributors
"""Smoke tests for forwarding core scaffolding."""

import frappe
import unittest


class TestFreightLCSSmoke(unittest.TestCase):
	def test_masters_exist(self):
		for dt in ["Freight Airport", "Freight Seaport", "Freight Airline",
			"Freight Driver", "Freight Truck", "HS Tariff Code",
			"Freight Activity Code", "Freight Terminal", "Freight Waybill",
			"Freight Voucher", "LCS Subscription", "Freight Job Request"]:
			self.assertTrue(frappe.db.exists("DocType", dt), f"{dt} missing")

	def test_activity_codes_seeded(self):
		self.assertGreaterEqual(frappe.db.count("Freight Activity Code"), 22)

	def test_create_master(self):
		name = "TEST-JED"
		if not frappe.db.exists("Freight Airport", name):
			doc = frappe.get_doc({
				"doctype": "Freight Airport", "airport_name": name,
				"iata_code": "TST", "is_active": 1,
			}).insert(ignore_permissions=True)
			self.assertEqual(doc.name, name)
			doc.delete()

	def test_billing_status_api(self):
		from forwarding.api import get_billing_status_counts
		counts = get_billing_status_counts()
		self.assertIn("Billed", counts)
