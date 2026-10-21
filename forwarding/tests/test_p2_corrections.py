# Copyright (c) 2026, DVNKS Systems and contributors
"""The backend P2 items of the Phase 1 corrections review (forms: duplicates
and cleanup). Each piece of data has one owner record.

D1 cargo measures for every mode, D2 Container Movements off on Air, D3
Custom Clearance owns Bayan / D.O / duty, D4 second Shipment fields hidden,
D5 clearance tables moved to Custom Clearance, D6 ATD / ATA beside ETD /
ETA, D10 Sales Invoice section labels. Everything is rolled back.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from forwarding.api import job_360
from forwarding.forwarding.doctype.operations.operations import make_custom_clearance
from forwarding.patches.v1_0 import (
	move_clearance_fields_to_custom_clearance as fields_patch,
	move_clearance_tables_to_custom_clearance as tables_patch,
	reset_job_field_order,
	sales_invoice_section_labels,
)
from forwarding.tests.test_job_360 import make
from forwarding.tests.test_job_360_p2 import make_clearance

CARGO = ("packages", "net_weight", "gross_weight", "weight_uom", "cbm", "cargo_description")
D3_FIELDS = ("bayan_no", "bayan_date", "do_no", "do_date", "clearance_date", "duty_amount_company", "duty_amount_client")


def _field(doctype, fieldname):
	return frappe.get_meta(doctype).get_field(fieldname)


def _container(number="MSCU7654321"):
	return [{"container_no": number, "size": "20", "container_type": "GP"}]


class P2TestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		frappe.cache.delete_keys("job_360")


class TestJobLayout(P2TestCase):
	def test_d1_cargo_measures_show_for_every_mode(self):
		for fieldname in CARGO + ("cargo_details_section",):
			self.assertFalse(_field("Operations", fieldname).depends_on, fieldname)
			self.assertFalse(_field("Operations", fieldname).hidden, fieldname)
		chargeable = _field("Operations", "chargable_weight").depends_on
		self.assertIn("mode_of_shipment==\"Air\"", chargeable)
		self.assertIn("doc.chargable_weight", chargeable)
		# C6 still locks the measures while package rows exist.
		for fieldname in ("packages", "gross_weight", "cbm"):
			self.assertIn("package_details", _field("Operations", fieldname).read_only_depends_on)

	def test_d2_container_movements_off_on_air(self):
		for fieldname in ("transport_container_section", "transport_container_legs"):
			rule = _field("Operations", fieldname).depends_on
			self.assertIn("doc.mode_of_shipment!='Air'", rule)
			self.assertIn("transport_container_legs", rule)
		self.assertFalse(_field("Operations", "transport_package_legs").depends_on)

	def test_d3_clearance_fields_hidden_on_job(self):
		for fieldname in D3_FIELDS:
			self.assertTrue(_field("Operations", fieldname).hidden, fieldname)
		# The rest of Documents & D.O stays.
		for fieldname in ("type_of_clearance", "demurrage_date", "do_remarks", "clearance_docs_section"):
			self.assertFalse(_field("Operations", fieldname).hidden, fieldname)

	def test_d4_second_shipment_fields_hidden(self):
		for fieldname in ("volume", "no_of_pieces", "dimension"):
			self.assertTrue(_field("Operations", fieldname).hidden, fieldname)
		self.assertFalse(_field("Operations", "location_in_port").hidden)
		# Still worked out from the package rows.
		job = make(package_details=[{"length": 100, "width": 100, "height": 100, "weight": 10, "quantity": 3}])
		self.assertEqual(job.no_of_pieces, 3)
		self.assertAlmostEqual(job.volume, 3)

	def test_d5_clearance_tables_hidden_on_job(self):
		for fieldname in (
			"clearance_containers_section",
			"clearance_containers",
			"clearance_documents_section",
			"clearance_documents",
		):
			self.assertTrue(_field("Operations", fieldname).hidden, fieldname)

	def test_d6_atd_beside_etd_and_ata_beside_eta(self):
		names = [f.fieldname for f in frappe.get_meta("Operations").fields]
		start = names.index("schedule_section")
		self.assertEqual(
			names[start : start + 8],
			[
				"schedule_section",
				"etd_date",
				"atd_date",
				"atd_delay_reason",
				"column_break_schedule",
				"eta_date",
				"ata_date",
				"ata_delay_reason",
			],
		)
		self.assertFalse(_field("Operations", "ata_delay_reason").hidden)

	def test_d6_patch_drops_stale_field_order(self):
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocType",
				"doc_type": "Operations",
				"property": "field_order",
				"property_type": "Data",
				"value": json.dumps(["naming_series", "operation_id", "ata_date", "etd_date"]),
			}
		).insert(ignore_permissions=True)
		reset_job_field_order.execute()
		reset_job_field_order.execute()
		self.assertFalse(frappe.db.exists("Property Setter", {"doc_type": "Operations", "property": "field_order"}))


class TestCustomClearanceOwnsClearance(P2TestCase):
	def test_d3_clearance_has_the_fields(self):
		for fieldname, fieldtype in (
			("bayyan_number", "Data"),
			("bayyan_date", "Date"),
			("do_number", "Data"),
			("do_date", "Date"),
			("clearance_date", "Date"),
			("duty_amount_company", "Currency"),
			("duty_amount_client", "Currency"),
		):
			self.assertEqual(_field("Custom Clearance", fieldname).fieldtype, fieldtype, fieldname)

	def test_d3_patch_copies_into_empty_fields_only(self):
		job = make(mode_of_shipment="Sea")
		frappe.db.set_value(
			"Operations",
			job.name,
			{"bayan_no": "BY-OLD", "do_no": "DO-9", "duty_amount_company": 250, "clearance_date": nowdate()},
		)
		cc = make_clearance(job, bayyan_number="BY-KEEP")

		self.assertEqual(fields_patch.copy_job_fields([job.name]), {"clearances": 1, "fields": 3})
		values = frappe.db.get_value(
			"Custom Clearance", cc.name, ["bayyan_number", "do_number", "duty_amount_company", "clearance_date"], as_dict=True
		)
		self.assertEqual(values.bayyan_number, "BY-KEEP")
		self.assertEqual(values.do_number, "DO-9")
		self.assertEqual(values.duty_amount_company, 250)
		self.assertEqual(str(values.clearance_date), nowdate())
		# Again: nothing left to copy.
		self.assertEqual(fields_patch.copy_job_fields([job.name]), {"clearances": 0, "fields": 0})

	def test_d3_job_360_carries_clearance_summary(self):
		job = make(mode_of_shipment="Sea")
		make_clearance(job, do_number="DO-1", duty_amount_client=99, clearance_date=nowdate())
		frappe.cache.delete_keys("job_360")
		linked = job_360.get(job.name)["linked"]["custom_clearance"][0]
		for key in (
			"bayyan_number",
			"bayyan_date",
			"do_number",
			"do_date",
			"clearance_status",
			"clearance_date",
			"duty_amount_company",
			"duty_amount_client",
		):
			self.assertIn(key, linked)
		self.assertEqual(linked["do_number"], "DO-1")
		self.assertEqual(linked["duty_amount_client"], 99)

	def test_d3_make_custom_clearance_maps_old_job_values(self):
		job = make(mode_of_shipment="Sea")
		frappe.db.set_value("Operations", job.name, {"bayan_no": "BY-77", "do_no": "DO-77"})
		cc = make_custom_clearance(job.name)
		self.assertEqual((cc.bayyan_number, cc.do_number), ("BY-77", "DO-77"))

	def test_d5_clearance_has_the_tables(self):
		self.assertEqual(_field("Custom Clearance", "clearance_containers").options, "Operations Clearance Container")
		self.assertEqual(_field("Custom Clearance", "clearance_documents").options, "Operations Clearance Document")

	def test_d5_job_containers_go_to_the_clearance(self):
		job = make(mode_of_shipment="Sea", svc_customs_clearance=1, container_details=_container())
		self.assertFalse(job.get("clearance_containers"))

		cc = make_clearance(job)
		self.assertEqual([r.container_no for r in cc.clearance_containers], ["MSCU7654321"])
		self.assertEqual(cc.clearance_containers[0].container_type, "20' GP")
		self.assertEqual(cc.clearance_containers[0].clearance_status, "Pending")

		# A container added to the job later reaches the clearance on save.
		job.reload()
		job.append("container_details", {"container_no": "MSCU1111111", "size": "40", "container_type": "HC"})
		job.save()
		cc.reload()
		self.assertEqual([r.container_no for r in cc.clearance_containers], ["MSCU7654321", "MSCU1111111"])
		job.save()
		cc.reload()
		self.assertEqual(len(cc.clearance_containers), 2)

	def test_d5_patch_copies_rows_once(self):
		job = make(mode_of_shipment="Sea")
		job_rows = {
			"clearance_containers": [{"container_no": "OLDU0000001", "clearance_status": "Released", "release_date": nowdate()}],
			"clearance_documents": [{"document_type": "Permit", "document_number": "P-1"}],
		}
		for parentfield, rows in job_rows.items():
			for idx, row in enumerate(rows, 1):
				frappe.get_doc(
					{
						"doctype": tables_patch.TABLES[parentfield],
						"parent": job.name,
						"parenttype": "Operations",
						"parentfield": parentfield,
						"idx": idx,
						**row,
					}
				).db_insert()
		orphan = make(mode_of_shipment="Sea")
		frappe.get_doc(
			{
				"doctype": "Operations Clearance Container",
				"parent": orphan.name,
				"parenttype": "Operations",
				"parentfield": "clearance_containers",
				"container_no": "ORPH0000001",
			}
		).db_insert()
		cc = frappe.get_doc({"doctype": "Custom Clearance", "operations": job.name, "bayyan_number": "B", "bayyan_date": nowdate()})
		cc.name = f"CC-{job.name}"
		cc.db_insert()  # a clearance made before the move, with no rows

		result = tables_patch.copy_job_tables([job.name, orphan.name])
		self.assertEqual(
			result, {"copied_rows": 2, "clearances": 1, "skipped_has_rows": 0, "jobs_without_clearance": 1}
		)
		cc = frappe.get_doc("Custom Clearance", cc.name)
		self.assertEqual(cc.clearance_containers[0].container_no, "OLDU0000001")
		self.assertEqual(cc.clearance_containers[0].clearance_status, "Released")
		self.assertEqual(cc.clearance_documents[0].document_number, "P-1")
		# The job keeps its rows.
		self.assertEqual(len(frappe.get_doc("Operations", job.name).clearance_containers), 1)

		again = tables_patch.copy_job_tables([job.name])
		self.assertEqual(again["copied_rows"], 0)
		self.assertEqual(again["skipped_has_rows"], 2)


class TestSalesInvoiceLabels(P2TestCase):
	def test_d10_section_labels(self):
		sales_invoice_section_labels.execute()
		sales_invoice_section_labels.execute()
		meta = frappe.get_meta("Sales Invoice")
		self.assertEqual(meta.get_field("customer_section").label, "Details")
		self.assertEqual(meta.get_field("items_section").label, "Stock")
		self.assertEqual(meta.get_field("section_break_42").label, "Items")
		sections = [f.label for f in meta.fields if f.fieldtype == "Section Break"]
		self.assertEqual(sections.count("Items"), 1)
		self.assertEqual(
			frappe.db.count("Property Setter", {"doc_type": "Sales Invoice", "field_name": "customer_section", "property": "label"}),
			1,
		)
		purchase = frappe.get_meta("Purchase Invoice")
		self.assertEqual(purchase.get_field("sec_warehouse").label, "Stock")
		self.assertNotIn("Items", [f.label for f in purchase.fields if f.fieldtype == "Section Break"])
