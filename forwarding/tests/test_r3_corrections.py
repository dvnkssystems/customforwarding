# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 corrections, section 2 ("fix first"). Uses the site's own masters;
everything is rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from forwarding.forwarding.doctype.operations.operations import make_purchase_invoice, make_sales_invoice
from forwarding.tests.test_job_360 import ITEM, make, submit_job


class R3Case(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)


def sales_invoice(job, submit=False):
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": job.company,
			"customer": job.customer,
			"operations": job.name,
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"set_posting_time": 1,
			"items": [{"item_code": ITEM, "qty": 1, "rate": 100}],
		}
	)
	si.insert(ignore_permissions=True)
	if submit:
		si.submit()
	return si


class TestInvoiceOnlyAfterSubmit(R3Case):
	# R3-03 --------------------------------------------------------------------

	def test_draft_job_refuses_a_sales_invoice(self):
		job = make()
		with self.assertRaisesRegex(frappe.ValidationError, f"{job.name}.*still a draft"):
			sales_invoice(job)

	def test_draft_job_refuses_the_mappers(self):
		job = make()
		for mapper in (make_sales_invoice, make_purchase_invoice):
			with self.assertRaisesRegex(frappe.ValidationError, "still a draft"):
				mapper(job.name)

	def test_draft_job_refuses_a_purchase_invoice(self):
		job = make()
		company = job.company
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": company,
				"supplier": frappe.db.get_value("Supplier", {"disabled": 0}, "name"),
				"operations": job.name,
				"bill_no": "R3-03",
				"items": [{"item_code": ITEM, "qty": 1, "rate": 50}],
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Purchase Invoice against it"):
			pi.insert(ignore_permissions=True)

	def test_submitted_job_is_invoiced(self):
		job = submit_job(make())
		si = sales_invoice(job, submit=True)
		self.assertEqual(si.docstatus, 1)

	def test_cancelled_job_refuses(self):
		job = submit_job(make())
		job.cancel()
		# Frappe's own link check gets there first; either way it is refused.
		with self.assertRaisesRegex(frappe.ValidationError, "(?i)cancelled"):
			sales_invoice(job)

	def test_invoice_without_a_job_is_untouched(self):
		job = make()
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": job.company,
				"customer": job.customer,
				"posting_date": nowdate(),
				"due_date": nowdate(),
				"items": [{"item_code": ITEM, "qty": 1, "rate": 100}],
			}
		).insert(ignore_permissions=True)
		self.assertTrue(si.name)
