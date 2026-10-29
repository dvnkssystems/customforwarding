# Copyright (c) 2026, DVNKS Systems and contributors
"""Simran's retest of 29 Oct: VAT placeholder, Branch from Cost Center,
the job's Customer picker."""

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.job_rules import customer_query
from forwarding.party_360 import vat_number
from forwarding.purchase_invoice import branch_for_cost_center


class TestRetest29Oct(IntegrationTestCase):
	def test_zero_vat_is_no_vat(self):
		self.assertIsNone(vat_number(frappe._dict(tax_id="0")))
		self.assertIsNone(vat_number(frappe._dict(tax_id=" 000 ")))
		self.assertEqual(vat_number(frappe._dict(tax_id="0", custom_vat_registration_number="300000000000003")), "300000000000003")
		self.assertEqual(vat_number(frappe._dict(tax_id="310123456700003")), "310123456700003")

	def test_branch_from_cost_center(self):
		branch = frappe.db.get_value("Branch", {"cost_center": ["is", "set"]}, ["name", "cost_center"], as_dict=True)
		if not branch:
			self.skipTest("no Branch with a Cost Center on this site")
		self.assertEqual(branch_for_cost_center(branch.cost_center), branch.name)
		self.assertIsNone(branch_for_cost_center(None))

	def test_customer_picker_gives_name_and_city(self):
		rows = customer_query("Customer", "", "name", 0, 5, {})
		for row in rows:
			self.assertEqual(len(row), 2)
			self.assertTrue(frappe.db.exists("Customer", row[0]))
