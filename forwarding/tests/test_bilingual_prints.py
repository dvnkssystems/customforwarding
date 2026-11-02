# Copyright (c) 2026, DVNKS Systems and contributors
"""The bilingual "Bilingual Tax Invoice" and "Proof of Delivery" print formats.

Rendered from documents built in memory, so nothing is saved."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from forwarding import invoice_print, pod_print


def company():
	return frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name", limit=1)[0]


def make_job(**values):
	job = frappe.new_doc("Operations")
	job.update(
		{
			"company": company(),
			"name": "J-TEST-POD-0001",
			"mode_of_shipment": "Sea",
			"consignee": "POD Test Consignee",
			"awb_number": "MBL-POD-TEST-1",
			"vessel_name": "TEST VESSEL",
			"voyage_number": "V1",
			"delivery_address": "Warehouse 1, Dammam",
			"delivery_date": nowdate(),
			"gross_weight": 21500,
			"cargo_description": "Spare parts",
			**values,
		}
	)
	return job


def make_invoice():
	si = frappe.new_doc("Sales Invoice")
	si.update(
		{
			"company": company(),
			"customer": "POD Test Buyer",
			"customer_name": "POD Test Buyer",
			"tax_id": "311111111100003",
			"posting_date": nowdate(),
			"currency": "SAR",
			"conversion_rate": 1,
			"name": "SINV-TEST-BILINGUAL",
		}
	)
	si.append("items", {"item_code": "Clearance", "item_name": "Clearance", "qty": 1, "rate": 100, "amount": 100, "net_amount": 100, "name": "r1"})
	si.update({"total": 100, "net_total": 100, "total_taxes_and_charges": 15, "grand_total": 115})
	return si


class TestProofOfDelivery(IntegrationTestCase):
	def test_containers_are_listed(self):
		job = make_job()
		job.append("container_details", {"name": "c1", "container_no": "MSCU1234565", "size": "40", "container_type": "HC", "seal_no": "S1", "packages": 10, "weight": 12000})
		job.append("container_details", {"name": "c2", "container_no": "MSCU7654321", "size": "20", "packages": 5, "weight": 9500})
		c = pod_print.get_pod_context(job)
		self.assertEqual(c.unit, "containers")
		self.assertEqual([l.ref for l in c.lines], ["MSCU1234565", "MSCU7654321"])
		self.assertEqual(c.lines[0].kind, "40' HC")
		self.assertEqual(c.lines[0].weight, "12,000")
		self.assertEqual(c.bl_awb, "MBL-POD-TEST-1")
		self.assertEqual(c.carrier, "TEST VESSEL / V1")

	def test_picked_containers_only(self):
		job = make_job()
		job.append("container_details", {"name": "c1", "container_no": "A"})
		job.append("container_details", {"name": "c2", "container_no": "B"})
		frappe.form_dict.containers = "c2"
		try:
			self.assertEqual([l.ref for l in pod_print.get_pod_context(job).lines], ["B"])
		finally:
			frappe.form_dict.pop("containers", None)

	def test_packages_when_no_containers(self):
		job = make_job(mode_of_shipment="Air", air_line="Saudia Cargo", flight_number="SV985")
		job.append("package_details", {"package_type": "Pallet", "quantity": 4, "length": 120, "width": 80, "height": 100, "total_weight": 800})
		c = pod_print.get_pod_context(job)
		self.assertEqual(c.unit, "packages")
		self.assertEqual(c.lines[0].kind, "120x80x100 cm")
		self.assertEqual(c.carrier, "Saudia Cargo / SV985")

	def test_renders_bilingual(self):
		job = make_job()
		html = frappe.get_print("Operations", job.name, "Proof of Delivery", doc=job, no_letterhead=1)
		for text in ("PROOF OF DELIVERY", "إثبات التسليم", "Receiver's Signature", "Receiver's Stamp", "MBL-POD-TEST-1", "POD Test Consignee"):
			self.assertIn(text, html)


class TestBilingualTaxInvoice(IntegrationTestCase):
	def test_context_has_header_and_bank(self):
		c = invoice_print.get_tax_invoice_context(make_invoice())
		self.assertIn("logo", c.seller)
		self.assertIn("cr", c.seller)
		self.assertIsInstance(c.bank, dict)

	def test_renders_bilingual(self):
		si = make_invoice()
		html = frappe.get_print("Sales Invoice", si.name, "Bilingual Tax Invoice", doc=si, no_letterhead=1)
		for text in ("TAX INVOICE", "فاتورة ضريبية", "Bank Details", "بيانات البنك", "311111111100003"):
			self.assertIn(text, html)
