# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 2, stream 2: document rows (R2-14, R2-15), actual dates (R2-19),
cargo weights (R2-21), mode-specific fields (R2-22, R2-25), quote -> job
parties and the customer's Default Salesperson (R2-24, M-04), the Bayan
fields (M-11) and the 360 pages' date range (M-18).

Uses the site's own masters; everything is rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from forwarding.api import customer_360, job_360, supplier_360
from forwarding.job_events import customer_cache_key, supplier_cache_key
from forwarding.party_360 import date_range, in_range, ranged_cache_key
from forwarding.quote_to_job import make_operations_from_quote
from forwarding.tests.test_customer_360 import make_customer as _make_customer
from forwarding.tests.test_customer_360 import make_invoice, make_quote
from forwarding.tests.test_job_360 import _first, any_service_scope, make, submit_job
from forwarding.tests.test_supplier_360 import make_bill, make_clearance, make_supplier

TODAY = nowdate()


def make_customer(**values):
	# CR No and VAT number are mandatory on this site.
	return _make_customer(cr_no="1010999999", custom_vat_registration_number="300000000000003", **values)


def document_name():
	return _first("Document List")


def sales_people(count=2):
	people = frappe.get_all("Sales Person", filters={"is_group": 0}, pluck="name", limit=count)
	if len(people) < count:
		raise frappe.DoesNotExistError("Test needs two Sales Person records")
	return people


class R2Case(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)


class TestDocumentRows(R2Case):
	def test_a_row_needs_a_document(self):
		job = make()
		job.append("document_table", {"received": "No"})
		# Refused by validate_document_rows (R3-06) before Frappe's own check.
		with self.assertRaisesRegex(frappe.ValidationError, "has no Document"):
			job.save()

	def test_received_dates_the_row_and_unreceived_clears_it(self):
		job = make()
		job.append("document_table", {"document": document_name(), "received": "Yes"})
		job.save()
		row = job.document_table[-1]
		self.assertEqual(getdate(row.date), getdate(TODAY))

		row.received = "No"
		job.save()
		self.assertIsNone(job.document_table[-1].date)

	def test_attaching_a_file_marks_received_and_dates_it(self):
		job = make()
		job.append("document_table", {"document": document_name(), "attach": "/files/r2-test.pdf"})
		job.save()
		row = job.document_table[-1]
		self.assertEqual(row.received, "Yes")
		self.assertEqual(getdate(row.date), getdate(TODAY))

	def test_patch_drops_only_empty_rows(self):
		from forwarding.patches.v1_0.r2_default_salesperson_and_documents import drop_empty_document_rows

		job = make()
		job.append("document_table", {"document": document_name()})
		job.save()
		empty = frappe.get_doc(
			{
				"doctype": "Document Table",
				"parent": job.name,
				"parenttype": "Operations",
				"parentfield": "document_table",
				"idx": 99,
			}
		)
		empty.db_insert()
		kept = frappe.get_doc(
			{
				"doctype": "Document Table",
				"parent": job.name,
				"parenttype": "Operations",
				"parentfield": "document_table",
				"idx": 100,
				"remark": "named later",
			}
		)
		kept.db_insert()

		drop_empty_document_rows()
		self.assertFalse(frappe.db.exists("Document Table", empty.name))
		self.assertTrue(frappe.db.exists("Document Table", kept.name))


class TestActualDates(R2Case):
	def test_future_atd_is_refused(self):
		job = make()
		job.atd_date = add_days(TODAY, 1)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be after today"):
			job.save()

	def test_today_and_past_are_fine(self):
		job = make(atd_date=add_days(TODAY, -2), ata_date=TODAY)
		self.assertEqual(getdate(job.ata_date), getdate(TODAY))

	def test_future_ata_on_a_submitted_job_is_refused(self):
		job = make()
		submit_job(job)
		job.ata_date = add_days(TODAY, 3)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be after today"):
			job.save()

	def test_an_untouched_old_date_does_not_block_other_edits(self):
		job = make()
		frappe.db.set_value("Operations", job.name, "atd_date", add_days(TODAY, 5))
		job.reload()
		job.remarks = "edited"
		job.save()

	def test_record_actual_refuses_a_future_date(self):
		draft = make()
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be after today"):
			job_360.record_actual(draft.name, "atd", add_days(TODAY, 1))

		submitted = make()
		submit_job(submitted)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be after today"):
			job_360.record_actual(submitted.name, "ata", add_days(TODAY, 1))
		self.assertIsNone(frappe.db.get_value("Operations", submitted.name, "ata_date"))

		job_360.record_actual(submitted.name, "atd", TODAY)
		self.assertEqual(getdate(frappe.db.get_value("Operations", submitted.name, "atd_date")), getdate(TODAY))


class TestWeights(R2Case):
	def test_gross_below_net_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be less than net weight"):
			make(mode_of_shipment="Sea", net_weight=11, gross_weight=5)

	def test_equal_or_one_missing_is_fine(self):
		make(mode_of_shipment="Sea", net_weight=11, gross_weight=11)
		make(mode_of_shipment="Sea", net_weight=11, gross_weight=0)
		make(mode_of_shipment="Sea", net_weight=0, gross_weight=4)


class TestModeFields(R2Case):
	def test_fields_follow_the_mode(self):
		meta = frappe.get_meta("Operations")
		self.assertEqual(meta.get_field("chargable_weight").depends_on, 'eval:doc.mode_of_shipment=="Air"')
		self.assertEqual(meta.get_field("air_line").depends_on, 'eval:doc.mode_of_shipment=="Air"')
		self.assertEqual(meta.get_field("carrier").depends_on, 'eval:doc.mode_of_shipment!="Air"')
		self.assertEqual(meta.get_field("shipping_line").depends_on, 'eval:doc.mode_of_shipment!="Air"')
		self.assertTrue(frappe.get_meta("Document Table").get_field("document").reqd)


class TestSalesperson(R2Case):
	def test_default_salesperson_fills_a_new_job(self):
		first, second = sales_people()
		customer = make_customer(default_salesperson=first)
		self.assertEqual(customer_360.default_salesperson(customer.name), first)

		job = make(customer=customer.name)
		self.assertEqual(job.salesman, first)

		chosen = make(customer=customer.name, salesman=second)
		self.assertEqual(chosen.salesman, second, "a salesman picked on the job is kept")

	def test_sales_team_is_the_fallback(self):
		first, _second = sales_people()
		customer = make_customer(sales_team=[{"sales_person": first, "allocated_percentage": 100}])
		self.assertEqual(customer_360.default_salesperson(customer.name), first)

	def test_customer_page_shows_the_default(self):
		first, _second = sales_people()
		customer = make_customer(default_salesperson=first)
		frappe.cache.delete_value(customer_cache_key(customer.name))
		header = customer_360.get(customer.name)["customer"]
		self.assertEqual(header["salesman"], first)
		self.assertEqual(header["default_salesman"], first)


class TestQuoteToJob(R2Case):
	def test_air_quote_fills_air_line_only_and_the_parties(self):
		first, _second = sales_people()
		customer = make_customer(default_salesperson=first)
		commodity = _first("Commodity")
		quote = make_quote(customer.name, mode="AIR", carrier="Saudia Cargo", cargo_details=commodity, submit=True)

		job = make_operations_from_quote(quote.name)
		self.assertEqual(job.mode_of_shipment, "Air")
		self.assertEqual(job.air_line, "Saudia Cargo")
		self.assertFalse(job.carrier, "the airline is not kept in Carrier as well")
		self.assertEqual(job.customer, customer.name)
		self.assertEqual(job.salesman, first)
		self.assertEqual(job.commodity, commodity)

	def test_saving_adds_the_consignee(self):
		customer = make_customer()
		quote = make_quote(customer.name, mode="SEA", submit=True)
		job = make_operations_from_quote(quote.name)
		self.assertFalse(job.consignee, "no Consignee record yet")

		job.update(
			{
				"company": _first("Company"),
				"branch": _first("Branch", {"abbreviation": ["is", "set"]}),
				"job_type": "Import",
				"scope_of_work": any_service_scope(),
				"port_of_loading": None,
				"port_of_destination": None,
			}
		)
		job.insert(ignore_permissions=True)
		self.assertEqual(job.consignee, customer.customer_name)
		self.assertTrue(frappe.db.exists("Consignee", customer.customer_name))

		again = make_operations_from_quote(quote.name)
		self.assertEqual(again.consignee, customer.customer_name, "an existing Consignee is matched")


class TestBayan(R2Case):
	def test_not_required_on_a_draft_clearance(self):
		job = make(mode_of_shipment="Sea")
		cc = frappe.get_doc({"doctype": "Custom Clearance", "operations": job.name, "clearance_status": "Draft"})
		cc.insert(ignore_permissions=True)
		self.assertFalse(cc.bayyan_number)

	def test_required_from_submitted_on(self):
		job = make(mode_of_shipment="Sea")
		cc = frappe.get_doc({"doctype": "Custom Clearance", "operations": job.name, "clearance_status": "Draft"})
		cc.insert(ignore_permissions=True)
		cc.reload()
		cc.clearance_status = "Submitted to Customs"
		with self.assertRaisesRegex(frappe.MandatoryError, "Bayan"):
			cc.save()
		cc.reload()
		cc.clearance_status = "Submitted to Customs"
		cc.bayyan_number = "2002"
		cc.bayyan_date = TODAY
		cc.save()

	def test_form_rule(self):
		meta = frappe.get_meta("Custom Clearance")
		for fieldname in ("bayyan_number", "bayyan_date"):
			df = meta.get_field(fieldname)
			self.assertFalse(df.reqd)
			self.assertIn("Draft", df.mandatory_depends_on)


class TestDateRangeHelpers(R2Case):
	def test_helpers(self):
		self.assertIsNone(date_range(None, None))
		self.assertEqual(ranged_cache_key("k", None), "k")
		rng = date_range("2026-01-01", "2026-01-31")
		self.assertEqual(ranged_cache_key("k", rng), "k|2026-01-01|2026-01-31")
		rows = [{"d": "2025-12-31"}, {"d": "2026-01-15"}, {"d": None}]
		self.assertEqual(in_range(rows, "d", rng), [{"d": "2026-01-15"}])
		self.assertEqual(len(in_range(rows, "d", None)), 3)
		self.assertEqual(in_range(rows, "d", date_range(None, "2025-12-31")), [{"d": "2025-12-31"}])
		with self.assertRaises(frappe.ValidationError):
			date_range("2026-02-01", "2026-01-01")


class TestCustomer360Range(R2Case):
	def test_range_narrows_lists_and_counts_not_balances(self):
		customer = make_customer().name
		old_job = make(customer=customer, date=add_days(TODAY, -60))
		new_job = make(customer=customer)
		make_quote(customer, validity_in_days=30, date=add_days(TODAY, -60))
		make_quote(customer, validity_in_days=30)
		make_invoice(customer, 100, due_in_days=-60, job=old_job.name)
		make_invoice(customer, 200, job=new_job.name)

		frappe.cache.delete_value(customer_cache_key(customer))
		everything = customer_360.get(customer)
		self.assertEqual(everything["kpis"]["active_jobs"], 2)
		self.assertEqual(everything["kpis"]["open_quotes"], 2)
		self.assertEqual(len(everything["jobs"]), 2)
		self.assertEqual(len(everything["invoices"]), 2)

		recent = customer_360.get(customer, from_date=add_days(TODAY, -7), to_date=TODAY)
		self.assertEqual([j["name"] for j in recent["jobs"]], [new_job.name])
		self.assertEqual(recent["kpis"]["active_jobs"], 1)
		self.assertEqual(recent["kpis"]["open_quotes"], 1)
		self.assertEqual(len(recent["quotes"]), 1)
		self.assertEqual(len(recent["invoices"]), 1)
		# Balances stay as of today, whatever the range.
		self.assertEqual(recent["kpis"]["outstanding"], everything["kpis"]["outstanding"])
		self.assertEqual(recent["kpis"]["overdue"], everything["kpis"]["overdue"])

		# Each range is cached on its own, and clearing the customer clears them all.
		ranged = ranged_cache_key(customer_cache_key(customer), date_range(add_days(TODAY, -7), TODAY))
		self.assertIsNotNone(frappe.cache.get_value(ranged))
		self.assertEqual(len(customer_360.get(customer)["jobs"]), 2, "no range is unchanged")
		from forwarding.job_events import clear_customer_cache

		clear_customer_cache(customer)
		self.assertIsNone(frappe.cache.get_value(ranged))


class TestSupplier360Range(R2Case):
	def test_range_narrows_services_jobs_and_bills(self):
		supplier = make_supplier().name
		old_job = make(mode_of_shipment="Sea", date=add_days(TODAY, -60))
		new_job = make(mode_of_shipment="Sea")
		old_cc = make_clearance(old_job, broker=supplier)
		frappe.db.set_value("Custom Clearance", old_cc.name, "start_date", add_days(TODAY, -60))
		make_clearance(new_job, broker=supplier)
		make_bill(supplier, 100, due_in_days=-60, job=old_job.name)
		make_bill(supplier, 200, job=new_job.name)

		frappe.cache.delete_value(supplier_cache_key(supplier))
		everything = supplier_360.get(supplier)
		self.assertEqual(len(everything["services"]), 2)
		self.assertEqual(everything["kpis"]["open_services"], 2)
		self.assertEqual(len(everything["jobs"]), 2)
		self.assertEqual(len(everything["invoices"]), 2)

		recent = supplier_360.get(supplier, from_date=add_days(TODAY, -7))
		self.assertEqual(len(recent["services"]), 1)
		self.assertEqual(recent["kpis"]["open_services"], 1)
		self.assertEqual([j["name"] for j in recent["jobs"]], [new_job.name])
		self.assertEqual(recent["kpis"]["active_jobs"], 1)
		self.assertEqual(len(recent["invoices"]), 1)
		self.assertEqual(recent["kpis"]["payable_outstanding"], everything["kpis"]["payable_outstanding"])
		self.assertEqual(recent["kpis"]["billed_this_year"], everything["kpis"]["billed_this_year"])
