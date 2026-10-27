# Copyright (c) 2026, DVNKS Systems and contributors
"""Credit notes against a submitted Sales Invoice (Addendum A-11)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from forwarding import credit_note
from forwarding.tests.test_job_360 import ITEM, ensure_submitted, make


def submitted_invoice(job, amount=1000):
	"""A submitted Sales Invoice on the job, with the company's default VAT."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges
	from frappe.utils import nowdate

	ensure_submitted(job)
	template = frappe.db.get_value(
		"Sales Taxes and Charges Template", {"company": job.company, "is_default": 1, "disabled": 0}
	)
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": job.company,
			"customer": job.customer,
			"operations": job.name,
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"set_posting_time": 1,
			"taxes_and_charges": template,
			"items": [{"item_code": ITEM, "qty": 1, "rate": amount}],
		}
	)
	if template:
		si.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", template))
	si.insert(ignore_permissions=True)
	si.submit()
	return si


class TestCreditNote(IntegrationTestCase):
	def setUp(self):
		self.job = make()
		try:
			self.invoice = submitted_invoice(self.job, amount=1000)
		except frappe.ValidationError as e:
			self.skipTest(f"cannot submit a test invoice on this site: {e}")

	def note(self, name):
		return frappe.get_doc("Sales Invoice", name)

	def test_full_credit_note(self):
		note = self.note(credit_note.make_credit_note(self.invoice.name, "Billed twice"))
		self.assertEqual((note.is_return, note.return_against, note.docstatus), (1, self.invoice.name, 0))
		self.assertEqual(note.custom_return_reason, "Billed twice")
		self.assertEqual(note.operations, self.job.name)
		self.assertAlmostEqual(abs(flt(note.grand_total)), flt(self.invoice.grand_total), places=2)

	def test_partial_credit_note_scales_the_rates(self):
		amount = flt(self.invoice.grand_total) / 4
		note = self.note(credit_note.make_credit_note(self.invoice.name, "Discount agreed", amount))
		self.assertAlmostEqual(abs(flt(note.grand_total)), amount, delta=0.05)
		self.assertEqual(note.items[0].qty, -self.invoice.items[0].qty)

	def test_reason_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			credit_note.make_credit_note(self.invoice.name, "  ")

	def test_not_more_than_the_invoice(self):
		with self.assertRaises(frappe.ValidationError):
			credit_note.make_credit_note(self.invoice.name, "Too much", flt(self.invoice.grand_total) + 10)

	def test_a_second_credit_note_is_refused_with_a_reason(self):
		credit_note.make_credit_note(self.invoice.name, "First", flt(self.invoice.grand_total) / 2)
		with self.assertRaises(frappe.ValidationError) as caught:
			credit_note.make_credit_note(self.invoice.name, "Second", 10)
		self.assertIn("already has credit note", str(caught.exception))

	def test_an_unpaid_invoice_is_reduced_by_its_credit_note(self):
		note = self.note(credit_note.make_credit_note(self.invoice.name, "Overbilled", 115))
		note.submit()
		self.assertAlmostEqual(
			flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")),
			flt(self.invoice.grand_total) - 115,
			delta=0.05,
		)

	def test_job_billed_is_net_of_credit_notes(self):
		from forwarding.api import job_360

		note = self.note(credit_note.make_credit_note(self.invoice.name, "Overbilled", 115))
		note.submit()
		kpis = job_360.build(self.job.name)["kpis"]
		self.assertAlmostEqual(kpis["billed"], flt(self.invoice.grand_total) - 115, delta=0.05)
		self.assertAlmostEqual(kpis["collected"], 0, delta=0.05)
