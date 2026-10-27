# Copyright (c) 2026, DVNKS Systems and contributors
"""A bill's job decides its Project, Branch and Cost Center (A-02, A-03)."""

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import purchase_invoice
from forwarding.party_360 import default_company
from forwarding.tests.test_job_360 import ITEM, _first, make


def bill(job=None, **values):
	"""An unsaved Purchase Invoice with one row."""
	return frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": default_company(),
			"operations": job,
			"items": [{"item_code": ITEM, "qty": 1, "rate": 100}],
			**values,
		}
	)


class TestJobBill(IntegrationTestCase):
	def setUp(self):
		company = default_company()
		centres = frappe.get_all("Cost Center", filters={"company": company, "is_group": 0}, pluck="name", limit=2)
		if len(centres) < 2:
			self.skipTest("needs two cost centers")
		self.job_cc, self.other_cc = centres
		self.job = make()
		self.job.db_set("cost_center", self.job_cc)
		self.branch = self.job.branch

	def test_job_overrides_header_and_rows(self):
		doc = bill(self.job.name, cost_center=self.other_cc, project=None)
		doc.items[0].cost_center = self.other_cc
		purchase_invoice.fill_from_job(doc)
		for row in (doc, doc.items[0]):
			self.assertEqual(row.cost_center, self.job_cc)
			self.assertEqual(row.branch, self.branch)
			self.assertTrue(row.project)

	def test_no_job_clears_a_job_project(self):
		other = make()
		if not frappe.db.exists("Project", other.name):
			self.skipTest("jobs have no Project on this site")
		doc = bill(None, project=other.name)
		doc.items[0].project = other.name
		purchase_invoice.fill_from_job(doc)
		self.assertIsNone(doc.project)
		self.assertIsNone(doc.items[0].project)

	def test_no_job_keeps_another_project(self):
		project = _first("Project", {"name": ["not in", frappe.get_all("Operations", pluck="name")]})
		if not project:
			self.skipTest("no non-job Project")
		doc = bill(None, project=project)
		purchase_invoice.fill_from_job(doc)
		self.assertEqual(doc.project, project)

	def test_literal_company_default_on_a_row(self):
		# A-05: a row that reached the server as ":Company".
		doc = bill(None, cost_center=self.other_cc)
		doc.items[0].cost_center = ":Company"
		purchase_invoice.fill_from_job(doc)
		self.assertEqual(doc.items[0].cost_center, self.other_cc)

	def test_due_date_from_the_credit_period(self):
		# A-15: posting date + the supplier's Credit Period.
		from frappe.utils import add_days, getdate, nowdate

		supplier = frappe.get_all("Supplier", pluck="name", limit=1)
		if not supplier or not frappe.get_meta("Supplier").has_field("credit_period"):
			self.skipTest("no supplier / credit_period")
		frappe.db.set_value("Supplier", supplier[0], "credit_period", "30 Days")
		doc = bill(None, supplier=supplier[0], posting_date=nowdate(), due_date=nowdate())
		purchase_invoice.due_from_credit_period(doc)
		self.assertEqual(getdate(doc.due_date), getdate(add_days(nowdate(), 30)))

		later = add_days(nowdate(), 60)
		doc = bill(None, supplier=supplier[0], posting_date=nowdate(), due_date=later)
		purchase_invoice.due_from_credit_period(doc)
		self.assertEqual(getdate(doc.due_date), getdate(later))

	def test_payment_takes_the_bill_branch(self):
		# A-20: Branch from the bill it pays.
		invoice = frappe.get_all("Purchase Invoice", filters={"branch": ["is", "set"]}, fields=["name", "branch"], limit=1)
		if not invoice:
			self.skipTest("no Purchase Invoice with a branch")
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"references": [{"reference_doctype": "Purchase Invoice", "reference_name": invoice[0].name}],
			}
		)
		purchase_invoice.payment_branch_from_bill(pe)
		self.assertEqual(pe.branch, invoice[0].branch)
