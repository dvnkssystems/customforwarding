# Copyright (c) 2026, DVNKS Systems and contributors
"""VAT per invoice line (ONE Freight, 12 Nov): the three choices pick their
templates, the invoice VAT follows them, and ZATCA gets the right codes."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import line_vat
from forwarding.tests.test_customer_360 import make_customer

CATEGORY = line_vat.CATEGORY_FIELD


class TestLineVat(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Before anything is made, so a failing setUp is rolled back too.
		self.addCleanup(frappe.db.rollback)
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		if not frappe.get_meta("Item Tax Template").has_field(CATEGORY):
			self.skipTest("KSA Compliance is not installed")
		self.company = frappe.db.get_value("Company", {}, "name")
		self.abbr = frappe.get_cached_value("Company", self.company, "abbr")
		self.vat = self.account("LV VAT 15%")
		self.zero = self.account("LV VAT Zero")
		# Only this test's templates: others on the site are switched off.
		for name in frappe.get_all("Item Tax Template", filters={"company": self.company, "disabled": 0}, pluck="name"):
			frappe.db.set_value("Item Tax Template", name, "disabled", 1)
		self.std = self.template("LV Standard", "Standard rate", 15)
		self.zr = self.template("LV Zero", line_vat.ZERO_CATEGORY, 0)
		self.oos = self.template(
			"LV OOS",
			"Services outside scope of tax / Not subject to VAT || {manual entry}",
			0,
			reason="Disbursement paid on behalf of the customer",
		)
		self.customer = make_customer(custom_vat_registration_number="300000000000003", cr_no="1010101010").name

	def account(self, name):
		full = f"{name} - {self.abbr}"
		if frappe.db.exists("Account", full):
			return full
		parent = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 1, "root_type": "Liability"}, "name"
		)
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": name,
				"company": self.company,
				"parent_account": parent,
				"account_type": "Tax",
			}
		).insert(ignore_permissions=True)
		return doc.name

	def template(self, title, category, rate, reason=None):
		doc = frappe.get_doc(
			{
				"doctype": "Item Tax Template",
				"title": title,
				"company": self.company,
				CATEGORY: category,
				"custom_category_reason": reason,
				"taxes": [{"tax_type": self.vat, "tax_rate": rate}, {"tax_type": self.zero, "tax_rate": 0}],
			}
		).insert(ignore_permissions=True)
		return doc.name

	def item(self, name, default):
		if not frappe.db.exists("Item", name):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": name,
					"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			).insert(ignore_permissions=True)
		line_vat.set_item_default(name, default, self.company)
		return name

	def invoice(self, lines):
		doc = frappe.new_doc("Sales Invoice")
		doc.update(
			{
				"company": self.company,
				"customer": self.customer,
				"currency": frappe.get_cached_value("Company", self.company, "default_currency"),
				"posting_date": frappe.utils.nowdate(),
				"due_date": frappe.utils.nowdate(),
				"taxes": [
					{
						"charge_type": "On Net Total",
						"account_head": self.vat,
						"description": "VAT 15%",
						"rate": 15,
						"cost_center": frappe.get_cached_value("Company", self.company, "cost_center"),
					}
				],
			}
		)
		for item_code, rate, vat_type in lines:
			doc.append("items", {"item_code": item_code, "qty": 1, "rate": rate, "vat_type": vat_type})
		doc.set_missing_values()
		doc.run_method("before_validate")
		doc.calculate_taxes_and_totals()
		return doc

	def test_templates_found_by_zatca_category(self):
		self.assertEqual(
			line_vat.templates(self.company),
			{line_vat.STANDARD: self.std, line_vat.ZERO: self.zr, line_vat.OUT_OF_SCOPE: self.oos},
		)

	def test_item_lists_all_three_with_its_default_first(self):
		self.item("LV Freight", line_vat.ZERO)
		rows = [r.item_tax_template for r in frappe.get_doc("Item", "LV Freight").taxes]
		self.assertEqual(rows, [self.zr, self.std, self.oos])

	def test_line_default_comes_from_the_charge(self):
		freight = self.item("LV Freight", line_vat.ZERO)
		clearance = self.item("LV Clearance", line_vat.STANDARD)
		doc = self.invoice([(freight, 1000, None), (clearance, 500, None)])
		self.assertEqual([r.vat_type for r in doc.items], [line_vat.ZERO, line_vat.STANDARD])
		self.assertEqual(doc.total_taxes_and_charges, 75)

	def test_changing_a_line_changes_the_invoice_vat(self):
		freight = self.item("LV Freight", line_vat.ZERO)
		clearance = self.item("LV Clearance", line_vat.STANDARD)
		duty = self.item("LV Duty", line_vat.OUT_OF_SCOPE)
		doc = self.invoice(
			[(freight, 1000, line_vat.STANDARD), (clearance, 500, line_vat.OUT_OF_SCOPE), (duty, 200, None)]
		)
		self.assertEqual([r.item_tax_template for r in doc.items], [self.std, self.oos, self.oos])
		self.assertEqual(doc.total_taxes_and_charges, 150)
		self.assertEqual(doc.grand_total, 1850)

	def test_choice_survives_erpnext_template_check(self):
		# ERPNext puts the Item's first template back when the line's is not
		# among the Item's; all three are listed, so the choice stays.
		freight = self.item("LV Freight", line_vat.ZERO)
		doc = self.invoice([(freight, 1000, line_vat.STANDARD)])
		doc.insert(ignore_permissions=True)
		doc.reload()
		self.assertEqual((doc.items[0].vat_type, doc.items[0].item_tax_template), (line_vat.STANDARD, self.std))
		self.assertEqual(doc.total_taxes_and_charges, 150)

	def test_zatca_reason_codes(self):
		from ksa_compliance.standard_doctypes.tax_category import map_tax_category

		std = map_tax_category(item_tax_template_id=self.std)
		zero = map_tax_category(item_tax_template_id=self.zr)
		oos = map_tax_category(item_tax_template_id=self.oos)
		self.assertEqual(std.tax_category_code, "S")
		self.assertEqual((zero.tax_category_code, zero.reason_code), ("Z", "VATEX-SA-34-1"))
		self.assertEqual((oos.tax_category_code, oos.reason_code), ("O", "VATEX-SA-OOS"))

	def test_options_for_the_form(self):
		opts = line_vat.options(self.company)
		self.assertEqual([o["vat_type"] for o in opts], list(line_vat.VAT_TYPES))
		self.assertEqual(opts[0]["item_tax_rate"][self.vat], 15)
		self.assertEqual(opts[2]["item_tax_rate"][self.vat], 0)
