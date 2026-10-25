# Copyright (c) 2026, DVNKS Systems and contributors
"""The three blockers from the Phase 1 retest: Get PDF, a zero-value invoice
marking the job Paid, and ops fields locked on a submitted job. Everything is
rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import print_pdf
from forwarding.job_events import get_billing_status
from forwarding.tests.test_job_360 import job_billing, make, make_sales_invoice, submit_job

OPS_FIELDS = ("etd_date", "atd_date", "eta_date", "ata_date", "vessel_name", "flight_number", "cutoffs", "operations_status")


class BlockerTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)


class TestGetPdf(BlockerTestCase):
	def test_override_is_hooked(self):
		self.assertEqual(
			frappe.get_hooks("override_whitelisted_methods")["frappe.utils.print_format.download_pdf"][-1],
			"forwarding.print_pdf.download_pdf",
		)

	def test_none_generator_falls_back_to_default(self):
		job = make()
		for sent in ("None", "", None, "chrome"):
			with patch.object(print_pdf, "frappe_download_pdf") as original:
				print_pdf.download_pdf("Operations", job.name, format="Arrival Notice", pdf_generator=sent, letterhead="None")
			kwargs = original.call_args.kwargs
			self.assertEqual(kwargs["pdf_generator"], "chrome" if sent == "chrome" else None, sent)
			self.assertIsNone(kwargs["letterhead"])

	def test_job_print_formats_name_a_generator(self):
		for name in ("Arrival Notice", "Job Delivery Note"):
			self.assertEqual(frappe.db.get_value("Print Format", name, "pdf_generator"), "wkhtmltopdf", name)


def make_zero_invoice(job):
	"""A draft invoice that bills nothing (a 0 rate alone picks up the price list)."""
	si = make_sales_invoice(job, submit=False)
	si.items[0].update({"price_list_rate": 0, "rate": 0})
	si.save()
	return si


class TestZeroValueInvoice(BlockerTestCase):
	def test_zero_invoice_cannot_be_submitted(self):
		job = make()
		si = make_zero_invoice(job)
		self.assertEqual(si.grand_total, 0)
		self.assertRaises(frappe.ValidationError, si.submit)
		self.assertEqual(get_billing_status(job.name), "No Invoice")

	def test_zero_total_is_not_paid(self):
		job = make()
		si = make_zero_invoice(job)
		# As JSI-26-0001 was: submitted before the rule existed.
		frappe.db.set_value("Sales Invoice", si.name, {"docstatus": 1, "outstanding_amount": 0})
		self.assertEqual(get_billing_status(job.name), "Invoiced")

	def test_invoice_without_job_is_not_checked(self):
		from forwarding.sales_invoice import block_zero_value_job_invoice

		block_zero_value_job_invoice(frappe._dict(operations=None, grand_total=0))
		block_zero_value_job_invoice(frappe._dict(operations="X", grand_total=0, is_return=1))

	def test_paid_invoice_still_paid(self):
		job = make()
		make_sales_invoice(job, amount=100)
		self.assertEqual(job_billing(job), "Invoiced")


class TestSubmittedJobStaysEditable(BlockerTestCase):
	def test_ops_fields_allow_on_submit(self):
		meta = frappe.get_meta("Operations")
		for fieldname in OPS_FIELDS:
			self.assertTrue(meta.get_field(fieldname).allow_on_submit, fieldname)
		# Commercial fields stay locked.
		for fieldname in ("customer", "port_of_loading", "port_of_destination", "cost_table"):
			self.assertFalse(meta.get_field(fieldname).allow_on_submit, fieldname)
		for fieldname in ("deadline", "cutoff_status"):
			self.assertTrue(frappe.get_meta("Job Cutoff").get_field(fieldname).allow_on_submit, fieldname)

	def test_update_after_submit(self):
		job = make(job_type="Export", mode_of_shipment="Sea", free_time_days=5, eta_date=nowdate())
		submit_job(job)
		self.assertTrue(job.cutoffs)

		job.reload()
		job.atd_date = nowdate()
		# An actual date cannot be after today (R2-19).
		job.ata_date = nowdate()
		job.vessel_name = "MSC TEST"
		job.cutoffs[0].deadline = f"{add_days(nowdate(), -1)} 10:00:00"
		# An export's free time counts from Container Pickup (R3-52).
		next(r for r in job.cutoffs if r.milestone == "Container Pickup").deadline = f"{nowdate()} 08:00:00"
		job.append("container_details", {"container_no": "MSCU1234567", "size": "20", "container_type": "GP"})
		job.save()

		job.reload()
		self.assertEqual(job.vessel_name, "MSC TEST")
		self.assertEqual(str(job.free_time_expiry), add_days(nowdate(), 5))
		# ATD recorded: the shipment has left, every cut-off was met (R3-54).
		self.assertEqual(job.cutoffs[0].cutoff_status, "Done")

	def test_locked_field_still_refused(self):
		job = make()
		submit_job(job)
		job.reload()
		job.port_of_loading = frappe.db.get_value("Port", {"name": ["!=", job.port_of_loading or ""]}, "name")
		self.assertRaises(frappe.UpdateAfterSubmitError, job.save)


class TestRepairPrintFormats(BlockerTestCase):
	def test_missing_image_becomes_header_and_footer_drops(self):
		from forwarding.patches.v1_0 import repair_print_formats as repair

		html = '<img src="/files/gone%20one.png" width="100%"><p>x</p><img src="/files/gone-two.png">'
		self.assertEqual(repair.without_missing_images(html, "<h1>Co</h1>"), "<h1>Co</h1><p>x</p>")
		# Jinja and remote sources are not files on this site.
		kept = '<img src="{{ doc.logo }}"><img src="https://example.com/a.png">'
		self.assertEqual(repair.without_missing_images(kept, "H"), kept)

	def test_invoice_format_repaired_once(self):
		from forwarding.patches.v1_0 import repair_print_formats as repair

		pf = frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": "_Test Broken Invoice",
				"doc_type": "Sales Invoice",
				"standard": "No",
				"custom_format": 1,
				"print_format_type": "Jinja",
				"html": (
					'<img src="/files/gone.png">{{ doc.name }} 311865189200003'
					"<!--{{ frappe.db.get_value('Address', doc.address, 'city') }}-->"
					'<img class="qr-code" src={{ doc.ksa_einv_qr}}>'
				),
			}
		).insert(ignore_permissions=True)
		repair.execute()
		repair.execute()
		html = frappe.db.get_value("Print Format", pf.name, "html")
		self.assertNotIn("doc.address", html)
		self.assertNotIn("311865189200003", html)
		self.assertNotIn("/files/gone.png", html)
		self.assertIn("{{ doc.company }}", html)
		self.assertEqual(html.count("{% if doc.ksa_einv_qr %}"), 1)
		self.assertIn("X", frappe.render_template(html, {"doc": frappe._dict(name="X", company="C")}))
