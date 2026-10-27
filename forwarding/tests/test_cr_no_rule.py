# Copyright (c) 2026, DVNKS Systems and contributors
"""CR No is 10 digits for Saudi customers and suppliers only (Simran, 27 Oct)."""

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import party_validation


def party(doctype, **values):
	return frappe.get_doc({"doctype": doctype, **values})


class TestCrNoRule(IntegrationTestCase):
	def test_saudi_supplier_needs_ten_digits(self):
		doc = party("Supplier", supplier_name="CR Test", supplier_group="DOMESTIC", country="Saudi Arabia", cr_no="123")
		with self.assertRaises(frappe.ValidationError):
			party_validation.validate_cr_no(doc)

	def test_overseas_group_is_not_checked(self):
		doc = party("Supplier", supplier_name="CR Test", supplier_group="OVERSEAS", cr_no="ABC-42")
		party_validation.validate_cr_no(doc)
		self.assertEqual(doc.cr_no, "ABC-42")

	def test_other_country_is_not_checked(self):
		doc = party("Supplier", supplier_name="CR Test", supplier_group="DOMESTIC", country="India", cr_no="U12345")
		party_validation.validate_cr_no(doc)

	def test_saudi_customer_ten_digits_pass(self):
		doc = party("Customer", customer_name="CR Test", customer_group="Commercial", cr_no="1010123456")
		party_validation.validate_cr_no(doc)
