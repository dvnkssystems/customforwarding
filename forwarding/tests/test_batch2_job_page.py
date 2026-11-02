# Copyright (c) 2026, DVNKS Systems and contributors
"""Batch 2 (job page), Simran's Round 3 retest: drafts are not running jobs
(item 3), + Add document on the job page (item 6) and a cut-off error that
names its row (item 10). Uses the site's own masters; everything is rolled
back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import banners
from forwarding.api import job_360
from forwarding.tests.test_job_360 import _first, make, submit_job


def codes(payload):
	return {b["rule_code"] for b in payload["banners"]}


def job_file(job, name="b2-test.txt"):
	"""A private File attached to the job, as the app's upload leaves it."""
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{frappe.generate_hash(length=8)}-{name}",
			"attached_to_doctype": "Operations",
			"attached_to_name": job,
			"is_private": 1,
			"content": b"batch 2 document",
		}
	).insert(ignore_permissions=True)


class Batch2Case(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		frappe.cache.delete_keys("job_360")


class TestDraftsAreNotRunning(Batch2Case):
	# Item 3: ATD / ATA and free-time alerts wait for Submit; the estimate
	# prompt stays, it is the draft's next step.

	def test_shipment_alerts_wait_for_submit(self):
		late = {
			"etd_date": add_days(nowdate(), -5),
			"eta_date": add_days(nowdate(), -2),
			"atd_date": None,
		}
		draft = frappe._dict(docstatus=0, operations_status="Open", **late)
		running = frappe._dict(docstatus=1, operations_status="Open", **late)
		ctx = {"today": nowdate(), "free_days_left": 1}
		self.assertFalse(banners.atd_missing(draft, ctx))
		self.assertFalse(banners.free_time_expiring(draft, ctx))
		self.assertTrue(banners.atd_missing(running, ctx))
		self.assertTrue(banners.free_time_expiring(running, ctx))

		draft.atd_date = running.atd_date = add_days(nowdate(), -4)
		self.assertFalse(banners.ata_missing(draft, ctx))
		self.assertTrue(banners.ata_missing(running, ctx))

	def test_draft_keeps_only_its_estimate_prompt_on_the_page(self):
		job = make(etd_date=add_days(nowdate(), -3), eta_date=add_days(nowdate(), -1))
		shown = codes(job_360.build(job.name))
		self.assertNotIn("B2", shown)
		self.assertIn("B9", shown, "a draft with no estimate is still prompted for one")

		submit_job(job)
		self.assertIn("B2", codes(job_360.build(job.name)))

	def test_worklist_follows_the_same_rule(self):
		job = make(etd_date=add_days(nowdate(), -3), eta_date=add_days(nowdate(), -1))
		on_worklist = {r.rule_code for r in banners.get_rules() if r.show_on_worklist}
		if "B2" not in on_worklist:
			self.skipTest("B2 is not shown on this site's worklist")

		def items():
			# Only this job, so the worklist's length limit cannot hide it.
			only = frappe.get_all(
				"Operations", filters={"name": job.name}, fields=job_360.WORKLIST_JOB_FIELDS
			)
			with patch.object(job_360, "_scoped_jobs", return_value=only):
				return {i["rule_code"] for i in job_360.build_worklist("Administrator", "all")["items"]}

		draft = items()
		self.assertFalse(draft & {"B2", "B3", "B4"}, draft)
		if "B9" in on_worklist:
			self.assertIn("B9", draft, "a draft with no estimate stays on the worklist")
		submit_job(job)
		self.assertIn("B2", items())

	def test_record_actual_refuses_a_draft(self):
		job = make(etd_date=add_days(nowdate(), -3))
		with self.assertRaisesRegex(frappe.ValidationError, "Submit job"):
			job_360.record_actual(job.name, "atd", nowdate())
		self.assertIsNone(frappe.db.get_value("Operations", job.name, "atd_date"))

	def test_record_actual_on_a_submitted_job(self):
		job = submit_job(make(etd_date=add_days(nowdate(), -3)))
		payload = job_360.record_actual(job.name, "atd", nowdate())
		self.assertEqual(str(payload["job"]["atd_date"]), nowdate())
		self.assertNotIn("B2", codes(payload))


class TestAddDocument(Batch2Case):
	# Item 6: + Add document appends a row to the job's own table.

	def setUp(self):
		super().setUp()
		self.document = _first("Document List")

	def _rows(self, job):
		return frappe.get_all(
			"Document Table",
			filters={"parenttype": "Operations", "parent": job, "parentfield": "document_table"},
			fields=["document", "attach", "received", "uploaded_by"],
			order_by="idx",
		)

	def test_adds_a_received_row_with_its_file(self):
		job = make()
		file = job_file(job.name)
		self.assertTrue(file.is_private)
		payload = job_360.add_document(job.name, self.document, file.file_url)

		rows = self._rows(job.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(
			(rows[0].document, rows[0].attach, rows[0].received, rows[0].uploaded_by),
			(self.document, file.file_url, "Yes", "Administrator"),
		)
		self.assertTrue(file.file_url.startswith("/private/files/"))
		self.assertIn(file.file_url, [d["attach"] for d in payload["documents"]])

	def test_a_submitted_job_takes_one_too(self):
		job = submit_job(make())
		file = job_file(job.name)
		job_360.add_document(job.name, self.document, file.file_url)
		self.assertEqual([r.attach for r in self._rows(job.name)], [file.file_url])
		self.assertEqual(frappe.db.get_value("Operations", job.name, "docstatus"), 1)

	def test_a_cancelled_job_does_not(self):
		job = submit_job(make())
		job.cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "cancelled"):
			job_360.add_document(job.name, self.document)

	def test_another_records_file_is_refused(self):
		job, other = make(), make()
		file = job_file(other.name)
		with self.assertRaisesRegex(frappe.ValidationError, "Upload the file"):
			job_360.add_document(job.name, self.document, file.file_url)
		self.assertEqual(self._rows(job.name), [])

	def test_unknown_document_type_is_refused(self):
		job = make()
		with self.assertRaisesRegex(frappe.ValidationError, "document type"):
			job_360.add_document(job.name, "No Such Document Type 9x")

	def test_needs_write_permission(self):
		job = make()
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				job_360.add_document(job.name, self.document)
		finally:
			frappe.set_user("Administrator")


class TestCutoffErrorNamesItsRow(Batch2Case):
	# Item 10: "<table> Row #<idx> (<milestone>): ...", which the app reads to
	# mark that row and scroll to it.

	def test_message_names_table_row_and_milestone(self):
		etd = add_days(nowdate(), 10)
		with self.assertRaisesRegex(
			frappe.ValidationError, r"^Cut-offs Row #2 \(Rail Cut-off\): Cut-off can't be after ETD"
		):
			make(
				job_type="Export",
				mode_of_shipment="Sea",
				etd_date=etd,
				cutoffs=[
					{"milestone": "Rail Cut-off", "deadline": f"{add_days(etd, -2)} 12:00:00"},
					{"milestone": "Rail Cut-off", "deadline": f"{add_days(etd, 3)} 12:00:00"},
				],
			)
