# Copyright (c) 2026, DVNKS Systems and contributors
"""Batch 1 (Simran, 2 Nov): party payable / receivable accounts, Debit To
from the job's branch, the buyer VAT warning."""

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.party_accounts import account_for, debit_to_from_job
from forwarding.sales_invoice import warn_missing_buyer_vat


def _branch_with(field):
	return frappe.db.get_value("Branch", {field: ["is", "set"]}, ["name", field], as_dict=True)


class TestBatch1Accounts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.home = frappe.db.get_value("Company", cls.company, "default_currency")

	def test_company_currency_takes_the_branch_account(self):
		branch = _branch_with("payable_account")
		if not branch:
			self.skipTest("no Branch with a payable account on this site")
		self.assertEqual(account_for("Payable", self.company, self.home, branch.name), branch.payable_account)

	def test_branch_without_account_keeps_the_party_account(self):
		default = frappe.db.get_value("Company", self.company, "default_payable_account")
		if not default:
			self.skipTest("no default payable account on this site")
		other = frappe.db.get_value(
			"Account",
			{"account_type": "Payable", "company": self.company, "account_currency": self.home, "is_group": 0, "name": ["!=", default]},
			"name",
		)
		self.assertEqual(account_for("Payable", self.company, self.home, None), default)
		if other:
			self.assertEqual(account_for("Payable", self.company, self.home, None, other), other)

	def test_foreign_currency_takes_that_currency_account(self):
		usd = frappe.db.get_value(
			"Account", {"account_type": "Payable", "company": self.company, "account_currency": "USD", "is_group": 0}, "name"
		)
		if not usd or self.home == "USD":
			self.skipTest("no USD payable account on this site")
		account = account_for("Payable", self.company, "USD", "RIYADH")
		self.assertEqual(frappe.db.get_value("Account", account, "account_currency"), "USD")

	def test_supplier_account_follows_its_currency(self):
		usd = frappe.db.get_value(
			"Account", {"account_type": "Payable", "company": self.company, "account_currency": "USD", "is_group": 0}, "name"
		)
		if not usd or not frappe.db.get_value("Company", self.company, "default_payable_account"):
			self.skipTest("payable accounts not set up on this site")
		supplier = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "_Test Batch1 Supplier",
				"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
				"default_currency": self.home,
				"tax_id": "310123456700003",
				"branch": "RIYADH" if frappe.db.exists("Branch", "RIYADH") else frappe.db.get_value("Branch", {}, "name"),
			}
		).insert(ignore_permissions=True)
		row = next(r for r in supplier.accounts if r.company == self.company)
		self.assertEqual(frappe.db.get_value("Account", row.account, "account_currency"), self.home)

		supplier.default_currency = "USD"
		supplier.save(ignore_permissions=True)
		row = next(r for r in supplier.accounts if r.company == self.company)
		self.assertEqual(frappe.db.get_value("Account", row.account, "account_currency"), "USD")

	def test_debit_to_from_the_job_branch(self):
		branch = _branch_with("receivable_account")
		job = branch and frappe.db.get_value("Operations", {"branch": branch.name}, "name")
		if not job:
			self.skipTest("no job on a branch with a receivable account")
		doc = frappe._dict(operations=job, company=self.company, currency=self.home, is_return=0, debit_to=None)
		debit_to_from_job(doc)
		self.assertEqual(doc.debit_to, branch.receivable_account)

		credit_note = frappe._dict(doc, is_return=1, debit_to="unchanged")
		debit_to_from_job(credit_note)
		self.assertEqual(credit_note.debit_to, "unchanged")

	def test_buyer_vat_warning(self):
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "_Test Batch1 Buyer",
				"customer_type": "Company",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0, "name": ["!=", "OVERSEAS"]}, "name"),
				"cr_no": "1010123456",
				"branch": "RIYADH" if frappe.db.exists("Branch", "RIYADH") else frappe.db.get_value("Branch", {}, "name"),
				"default_currency": self.home,
			}
		).insert(ignore_permissions=True)
		frappe.local.message_log = []
		warn_missing_buyer_vat(frappe._dict(customer=customer.name, company=self.company, is_return=0))
		self.assertTrue(any("VAT" in str(m) for m in frappe.local.message_log))

		customer.db_set("tax_id", "310123456700003")
		frappe.clear_document_cache("Customer", customer.name)
		frappe.local.message_log = []
		warn_missing_buyer_vat(frappe._dict(customer=customer.name, company=self.company, is_return=0))
		self.assertFalse(frappe.local.message_log)
