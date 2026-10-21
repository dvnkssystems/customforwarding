# Copyright (c) 2026, DVNKS Systems and contributors
"""The "next" items of the Phase 1 retest: quote to job, margins with no cost,
document totals on the 360 pages, cut-off back-fill, the same-port rule only
for freight forwarding, and fields hidden as repeats. Everything is rolled
back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding.api import job_360
from forwarding.patches.v1_0 import backfill_export_cutoffs
from forwarding.quote_to_job import make_operations_from_quote
from forwarding.tests.test_customer_360 import fresh, make_quote
from forwarding.tests.test_job_360 import CUSTOMER, make, make_sales_invoice


def _port(**filters):
	name = frappe.db.get_value("Port", filters, "name")
	if not name:
		raise frappe.DoesNotExistError(f"Test needs a Port matching {filters}")
	return name


class RetestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		frappe.cache.delete_keys("job_360")


class TestQuoteToJob(RetestCase):
	def test_air_quote(self):
		quote = make_quote(
			CUSTOMER,
			mode="AIR",
			carrier="Saudia Cargo",
			cargo="General cargo",
			cargo_details="Retest Widgets",
			date=add_days(nowdate(), -18),
			items=[{"description": "Air freight", "rate": 10, "units": 1, "amount": 10}],
		)
		job = make_operations_from_quote(quote.name)
		self.assertEqual(str(job.date), nowdate())
		self.assertEqual(str(job.posting_date), nowdate())
		self.assertEqual(job.air_line, "Saudia Cargo")
		self.assertFalse(job.vessel_name)
		if frappe.db.exists("Shipment Type", {"mode_of_shipment": "Air", "disabled": 0}):
			self.assertTrue(job.shipment_type)
		self.assertEqual(job.cargo_description, "Retest Widgets")
		# Picking the quote adds nothing; saving the job adds and links the commodity.
		self.assertFalse(job.commodity)
		self.assertFalse(frappe.db.exists("Commodity", "Retest Widgets"))
		job.update({"company": frappe.db.get_value("Company", {}, "name"), "branch": frappe.db.get_value("Branch", {"abbreviation": ["is", "set"]}), "job_type": "Import"})
		job.insert(ignore_permissions=True)
		self.assertEqual(job.commodity, "Retest Widgets")

	def test_sea_quote(self):
		quote = make_quote(CUSTOMER, mode="SEA", sea_shipment_type="FCL", cargo="Dg Goods", carrier="Nobody Lines")
		job = make_operations_from_quote(quote.name)
		self.assertFalse(job.vessel_name)
		self.assertFalse(job.air_line)
		self.assertTrue(job.dg_status)
		if frappe.db.exists("Shipment Type", "DG Cargo"):
			self.assertEqual(job.shipment_type, "DG Cargo")

	def test_existing_commodity_matched_ignoring_case(self):
		existing = frappe.db.get_value("Commodity", {}, "name")
		if not existing:
			self.skipTest("needs a Commodity")
		quote = make_quote(CUSTOMER, mode="SEA", cargo_details=existing.lower())
		before = frappe.db.count("Commodity")
		self.assertEqual(make_operations_from_quote(quote.name).commodity, existing)
		self.assertEqual(frappe.db.count("Commodity"), before)


class TestMarginWithoutCost(RetestCase):
	def test_no_cost_is_no_margin(self):
		job = make()
		make_sales_invoice(job, amount=100)
		kpis = job_360.get(job.name)["kpis"]
		self.assertGreater(kpis["revenue_total"], 0)
		self.assertIsNone(kpis["margin_pct"])

	def test_cost_amount_hidden(self):
		self.assertTrue(frappe.get_meta("Cost Table").get_field("amount").hidden)


class TestDocumentTotals(RetestCase):
	def test_customer_tile_has_total(self):
		job = make()
		job.append("document_table", {"document": frappe.db.get_value("Document List", {}, "name"), "received": "No"})
		job.save()
		kpis = fresh(CUSTOMER)["kpis"]
		self.assertIn("documents_total", kpis)
		self.assertGreaterEqual(kpis["documents_total"], kpis["documents_on_file"] + 1)


class TestCutoffBackfill(RetestCase):
	def test_open_export_jobs_get_defaults_once(self):
		job = make(job_type="Export", mode_of_shipment="Air")
		frappe.db.delete("Job Cutoff", {"parent": job.name})
		done = make(job_type="Export", mode_of_shipment="Air")
		frappe.db.delete("Job Cutoff", {"parent": done.name})
		frappe.db.set_value("Operations", done.name, "operations_status", "Closed")

		backfill_export_cutoffs.execute()
		backfill_export_cutoffs.execute()

		rows = frappe.get_all("Job Cutoff", filters={"parent": job.name}, pluck="milestone", order_by="idx")
		self.assertEqual(rows, ["SI Deadline", "Cargo Cut-off"])
		self.assertFalse(frappe.db.exists("Job Cutoff", {"parent": done.name}))


class TestSamePortOnlyForForwarding(RetestCase):
	def test_customs_only_job_may_use_one_location(self):
		port = _port(mode_of_shipment="Sea")
		job = make(mode_of_shipment="Sea", svc_customs_clearance=1, port_of_loading=port, port_of_destination=port)
		self.assertEqual(job.port_of_loading, job.port_of_destination)

	def test_forwarding_job_still_refused(self):
		port = _port(mode_of_shipment="Sea")
		self.assertRaises(
			frappe.ValidationError,
			make,
			mode_of_shipment="Sea",
			svc_freight_forwarding=1,
			port_of_loading=port,
			port_of_destination=port,
		)


class TestRepeatedDocumentDates(RetestCase):
	def test_hidden(self):
		meta = frappe.get_meta("Operations")
		for fieldname in ("docs_copy_received_date", "bl_receive_date", "original_docs_received_date", "saber_certificate_date"):
			self.assertTrue(meta.get_field(fieldname).hidden, fieldname)
