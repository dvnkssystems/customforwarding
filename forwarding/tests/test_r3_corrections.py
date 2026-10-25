# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 corrections, section 2 ("fix first"). Uses the site's own masters;
everything is rolled back."""

import os
import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from forwarding.forwarding.doctype.operations.operations import (
	make_purchase_invoice,
	make_sales_invoice,
	short_date,
)
from forwarding.tests.test_job_360 import ITEM, add_estimate, make, submit_job
from forwarding.tests.test_job_360_p2 import job_with_rows


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


class TestDocumentsAtClose(R3Case):
	# R3-07 --------------------------------------------------------------------

	def test_submit_is_not_held_by_documents(self):
		job = add_estimate(job_with_rows())
		frappe.clear_messages()
		job.submit()
		self.assertEqual(job.docstatus, 1)
		self.assertNotIn("Documents outstanding", str(frappe.message_log))

	def test_close_is_refused_with_documents_outstanding(self):
		job = submit_job(job_with_rows())
		job.operations_status = "Closed"
		with self.assertRaisesRegex(frappe.ValidationError, "Not marked received"):
			job.save()
		self.assertNotEqual(frappe.db.get_value("Operations", job.name, "operations_status"), "Closed")

	def test_close_through_set_value_is_refused(self):
		job = submit_job(job_with_rows())
		with self.assertRaisesRegex(frappe.ValidationError, "every document"):
			frappe.client.set_value("Operations", job.name, "operations_status", "Closed")

	def test_close_goes_through_once_everything_is_in(self):
		job = submit_job(job_with_rows())
		for row in job.document_table:
			row.received = "Yes"
		job.operations_status = "Closed"
		job.save()
		self.assertEqual(frappe.db.get_value("Operations", job.name, "operations_status"), "Closed")


class TestSubmitProblemsAtOnce(R3Case):
	# R3-08 --------------------------------------------------------------------

	def test_every_problem_in_one_message(self):
		job = make()
		job.reload()
		# A mandatory field gone missing (a save that skipped mandatory, or a
		# field made mandatory since) and no estimate: both, in one message.
		job.flags.ignore_mandatory = False
		mandatory = next(
			df.fieldname
			for df in job.meta.fields
			if df.reqd and df.fieldtype in ("Data", "Date", "Link") and df.fieldname not in ("company", "naming_series")
		)
		problems_before = job.submit_problems()
		self.assertTrue(any("estimate" in p for p in problems_before))
		job.set(mandatory, None)
		problems = job.submit_problems()
		self.assertGreaterEqual(len(problems), 2)
		self.assertTrue(any(job.meta.get_label(mandatory) in p for p in problems), problems)

	def test_single_message_lists_them(self):
		job = make()
		with self.assertRaises(frappe.ValidationError) as caught:
			job.submit()
		self.assertIn("Add an estimate", str(caught.exception))


class TestCutoffsBeforeEtd(R3Case):
	# R3-12 --------------------------------------------------------------------

	def test_cutoff_after_etd_is_refused(self):
		etd = add_days(nowdate(), 10)
		with self.assertRaisesRegex(frappe.ValidationError, r"Cut-off can't be after ETD"):
			make(
				job_type="Export",
				mode_of_shipment="Sea",
				etd_date=etd,
				cutoffs=[{"milestone": "Rail Cut-off", "deadline": f"{add_days(etd, 7)} 12:00:00"}],
			)

	def test_message_names_the_etd(self):
		etd = add_days(nowdate(), 10)
		with self.assertRaises(frappe.ValidationError) as caught:
			make(
				job_type="Export",
				mode_of_shipment="Sea",
				etd_date=etd,
				cutoffs=[{"milestone": "Rail Cut-off", "deadline": f"{add_days(etd, 1)} 08:00:00"}],
			)
		self.assertIn(f"({short_date(etd)})", str(caught.exception))

	def test_cutoff_on_or_before_etd_saves(self):
		etd = add_days(nowdate(), 10)
		job = make(
			job_type="Export",
			mode_of_shipment="Sea",
			etd_date=etd,
			cutoffs=[{"milestone": "Rail Cut-off", "deadline": f"{etd} 18:00:00"}],
		)
		self.assertTrue(job.name)

	def test_short_date(self):
		self.assertEqual(short_date(f"{getdate(nowdate()).year}-10-24"), "24 Oct")
		self.assertEqual(short_date("2031-10-04"), "4 Oct 2031")


class TestBlankDocumentRows(R3Case):
	# R3-06 --------------------------------------------------------------------

	def test_job_refuses_a_row_with_no_document(self):
		job = make()
		job.append("document_table", {"received": "No"})
		job.flags.ignore_mandatory = True  # the rule holds even then
		with self.assertRaisesRegex(frappe.ValidationError, "has no Document"):
			job.save()

	def test_submitted_job_refuses_it_too(self):
		job = submit_job(make())
		job.append("document_table", {"received": "No"})
		job.flags.ignore_mandatory = True
		with self.assertRaisesRegex(frappe.ValidationError, "has no Document"):
			job.save()

	def test_custom_clearance_refuses_a_blank_clearance_document(self):
		job = make()
		cc = frappe.get_doc(
			{
				"doctype": "Custom Clearance",
				"operations": job.name,
				"clearance_status": "Draft",
				"clearance_documents": [{"document_number": "X-1"}],
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Clearance Documents: row 1 has no"):
			cc.insert(ignore_permissions=True)

	def test_patch_drops_blank_rows_only(self):
		from forwarding.patches.v1_0 import r3_drop_blank_document_rows

		job = job_with_rows()
		named = len(job.document_table)
		for i in range(2):
			frappe.get_doc(
				{
					"doctype": "Document Table",
					"parent": job.name,
					"parenttype": "Operations",
					"parentfield": "document_table",
					"idx": named + i + 1,
					"received": "No",
				}
			).db_insert()
		r3_drop_blank_document_rows.execute()
		job.reload()
		self.assertEqual(len(job.document_table), named)
		self.assertEqual([r.idx for r in job.document_table], list(range(1, named + 1)))
		job.save()  # saves again


class TestDocumentsWarningAfterSave(R3Case):
	# R3-07 / R3-08: the save-time warning must not lead a refusal --------------

	def test_refused_save_carries_only_the_refusal(self):
		job = job_with_rows()
		job.append("document_table", {"received": "No"})
		frappe.clear_messages()
		with self.assertRaises(frappe.ValidationError):
			job.save()
		self.assertNotIn("Not marked received", str(frappe.message_log))

	def test_successful_save_still_warns(self):
		job = job_with_rows()
		frappe.clear_messages()
		job.save()
		self.assertIn("Not marked received", str(frappe.message_log))


def port_in(saudi):
	op = "=" if saudi else "!="
	name = frappe.db.get_value("Port", {"country": [op, "Saudi Arabia"]}, "name")
	if not name:
		raise unittest.SkipTest("needs a Saudi and a non-Saudi Port")
	return name


class TestHomeSide(R3Case):
	# R3-05 --------------------------------------------------------------------

	def test_import_arrives_in_saudi_arabia(self):
		job = make(job_type="Import", destination_country=None)
		self.assertEqual(job.destination_country, "Saudi Arabia")

	def test_export_leaves_from_saudi_arabia(self):
		job = make(job_type="Export", loading_country="SAUDI  ARABIA" if frappe.db.exists("Territory", "SAUDI  ARABIA") else None)
		self.assertEqual(job.loading_country, "Saudi Arabia")

	def test_import_refuses_a_foreign_port_of_discharge(self):
		with self.assertRaisesRegex(frappe.ValidationError, "must be a port in Saudi Arabia"):
			make(job_type="Import", port_of_destination=port_in(False))

	def test_export_refuses_a_foreign_port_of_loading(self):
		with self.assertRaisesRegex(frappe.ValidationError, "must be a port in Saudi Arabia"):
			make(job_type="Export", port_of_loading=port_in(False))

	def test_saudi_ports_and_the_other_side_are_free(self):
		job = make(job_type="Import", port_of_destination=port_in(True), port_of_loading=port_in(False))
		self.assertEqual(job.destination_country, "Saudi Arabia")

	def test_other_job_types_are_left_alone(self):
		other = frappe.db.get_value("Job Type", {"name": ["not in", ["Import", "Export"]]}, "name")
		if not other:
			self.skipTest("needs a third Job Type")
		job = make(job_type=other, port_of_destination=port_in(False), port_of_loading=port_in(False))
		self.assertNotEqual(job.destination_country, "Saudi Arabia")


class TestPrivateAttachments(R3Case):
	# R3-10 --------------------------------------------------------------------

	def file(self, job, name, private=0):
		return frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{name}-{frappe.generate_hash(length=6)}.txt",
				"content": b"bill of lading",
				"attached_to_doctype": "Operations",
				"attached_to_name": job.name,
				"is_private": private,
			}
		).insert(ignore_permissions=True)

	def test_upload_to_a_freight_record_is_made_private(self):
		from forwarding import private_files

		captured = {}
		with patch("frappe.handler.upload_file", lambda: captured.update(private=frappe.form_dict.is_private)):
			frappe.form_dict.update({"doctype": "Operations", "docname": "X", "is_private": 0})
			try:
				private_files.upload_file()
			finally:
				for key in ("doctype", "docname", "is_private"):
					frappe.form_dict.pop(key, None)
		self.assertEqual(captured["private"], 1)

	def test_upload_elsewhere_is_left_alone(self):
		from forwarding import private_files

		captured = {}
		with patch("frappe.handler.upload_file", lambda: captured.update(private=frappe.form_dict.is_private)):
			frappe.form_dict.update({"doctype": "User", "docname": "X", "is_private": 0})
			try:
				private_files.upload_file()
			finally:
				for key in ("doctype", "docname", "is_private"):
					frappe.form_dict.pop(key, None)
		self.assertEqual(captured["private"], 0)

	def test_public_file_on_a_job_goes_private(self):
		job = make()
		f = self.file(job, "r3-10-public")
		self.assertEqual(f.is_private, 1)
		self.assertTrue(f.file_url.startswith("/private/files/"))
		self.assertTrue(os.path.exists(f.get_full_path()))

	def test_patch_moves_public_files_and_rewrites_row_urls(self):
		from forwarding.patches.v1_0 import r3_private_attachments

		job = job_with_rows()
		with patch("forwarding.private_files.on_file_insert"):
			f = self.file(job, "r3-10-legacy")
		self.assertEqual(f.is_private, 0)
		frappe.db.set_value("Document Table", job.document_table[0].name, "attach", f.file_url)
		public_path = f.get_full_path()

		# Not undone on rollback: the test's rollback deletes the file where
		# it now is, through the insert's own rollback.
		with patch("frappe.core.doctype.file.file.File.on_rollback"):
			r3_private_attachments.execute()

		f.reload()
		self.assertEqual(f.is_private, 1)
		self.assertTrue(f.file_url.startswith("/private/files/"))
		self.assertTrue(os.path.exists(f.get_full_path()))
		self.assertFalse(os.path.exists(public_path))
		self.assertEqual(frappe.db.get_value("Document Table", job.document_table[0].name, "attach"), f.file_url)


class TestFormCleanUp(R3Case):
	# R3-33 --------------------------------------------------------------------

	def test_total_cost_is_the_estimate_cost(self):
		job = make(cost_table=[{"item_name": "A", "rate": 100, "cost": 60}, {"item_name": "B", "rate": 50, "cost": 15.5}])
		self.assertEqual(job.custom_total_cost, 75.5)
		meta = frappe.get_meta("Operations")
		self.assertTrue(meta.get_field("custom_total_cost").read_only)
		for fieldname in ("posting_date", "operation_id"):
			self.assertTrue(meta.get_field(fieldname).hidden, fieldname)
		for fieldname in ("operations_status", "billing_status"):
			self.assertTrue(meta.get_field(fieldname).read_only, fieldname)


class TestEstimateAndActual(R3Case):
	# R3-35 --------------------------------------------------------------------

	def test_payload_has_estimate_and_actuals(self):
		from forwarding.api import job_360
		from forwarding.tests.test_job_360 import make_sales_invoice
		from forwarding.tests.test_r2_job_lifecycle import make_purchase_invoice

		job = make(cost_table=[{"item_name": "Freight", "rate": 2000, "cost": 1500}])
		make_sales_invoice(job, amount=2300)
		make_purchase_invoice(job, amount=1600)
		frappe.cache.delete_keys("job_360")
		kpis = job_360.build(job.name)["kpis"]
		self.assertEqual((kpis["estimate_selling"], kpis["estimate_cost"]), (2000, 1500))
		self.assertEqual(kpis["estimate_margin_pct"], 25.0)
		self.assertEqual((kpis["actual_billed"], kpis["actual_cost"]), (2300, 1600))
		self.assertEqual(kpis["actual_margin_pct"], round((2300 - 1600) / 2300 * 100, 2))


class TestCutoffDeadline(R3Case):
	# R3-54 --------------------------------------------------------------------

	def test_sea_export_defaults(self):
		job = make(job_type="Export", mode_of_shipment="Sea", destination_country="Saudi Arabia")
		self.assertEqual([r.milestone for r in job.cutoffs], ["SI Deadline", "VGM Cut-off", "Cargo Cut-off", "Container Pickup"])

	def test_statuses(self):
		from frappe.utils import add_to_date, now_datetime

		from forwarding.forwarding.doctype.operations.operations import get_cutoff_status

		self.assertEqual(get_cutoff_status(add_to_date(now_datetime(), days=3)), "Upcoming")
		self.assertEqual(get_cutoff_status(add_to_date(now_datetime(), minutes=5)), "Due today")
		self.assertEqual(get_cutoff_status(add_to_date(now_datetime(), days=-1)), "Missed")
		self.assertEqual(get_cutoff_status(None, done=True), "Done")

	def test_patch_moves_latest_to_deadline(self):
		from forwarding.patches.v1_0 import r3_cutoff_deadline

		job = make(job_type="Export", mode_of_shipment="Sea", destination_country="Saudi Arabia")
		row = job.cutoffs[0]
		frappe.db.set_value("Job Cutoff", row.name, {"deadline": None, "latest": f"{add_days(nowdate(), 3)} 10:00:00"})
		r3_cutoff_deadline.execute()
		self.assertEqual(str(frappe.db.get_value("Job Cutoff", row.name, "deadline")), f"{add_days(nowdate(), 3)} 10:00:00")
		self.assertEqual(frappe.db.get_value("Job Cutoff", row.name, "cutoff_status"), "Upcoming")


class TestAtaAlertAfterDeparture(R3Case):
	# R3-55 --------------------------------------------------------------------

	def test_no_ata_alert_before_departure(self):
		from forwarding import banners

		job = frappe._dict(docstatus=0, operations_status="Open", etd_date=add_days(nowdate(), -5), eta_date=add_days(nowdate(), -1))
		ctx = {"today": nowdate()}
		self.assertTrue(banners.atd_missing(job, ctx))
		self.assertFalse(banners.ata_missing(job, ctx))
		job.atd_date = add_days(nowdate(), -5)
		self.assertTrue(banners.ata_missing(job, ctx))
		job.eta_date = add_days(nowdate(), 2)
		self.assertFalse(banners.ata_missing(job, ctx))
