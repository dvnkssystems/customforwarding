# Copyright (c) 2026, DVNKS Systems and contributors
"""The bilingual "Bilingual Tax Invoice" and "Proof of Delivery" print formats.

Rendered from documents built in memory, so nothing is saved."""

from unittest.mock import patch

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

	def test_title_follows_zatca_document_type(self):
		si = make_invoice()
		self.assertEqual(invoice_print.invoice_title(si, "311111111100003")["title"], "Tax Invoice")
		self.assertEqual(invoice_print.invoice_title(si, "")["title_ar"], "فاتورة ضريبية مبسطة")
		si.is_debit_note = 1
		self.assertEqual(invoice_print.invoice_title(si, "311111111100003")["title"], "Debit Note")
		si.is_return = 1
		self.assertEqual(invoice_print.invoice_title(si, "311111111100003")["title"], "Credit Note")


class TestInvoiceShipment(IntegrationTestCase):
	"""Vessel / voyage, ports, containers and the stamp (ONE Freight, 5 and 9 Nov)."""

	def test_container_size_type(self):
		self.assertEqual(invoice_print.container_size_type("40", "40GP"), "40' GP")
		self.assertEqual(invoice_print.container_size_type("40", "GP"), "40' GP")
		self.assertEqual(invoice_print.container_size_type("", "20RF"), "20' RF")
		self.assertEqual(invoice_print.container_size_type("", ""), "")

	def test_containers_listed_then_summarised(self):
		rows = [frappe._dict(container_no="mscu4821356", size="40", container_type="40GP", qty=1)]
		with patch("frappe.get_all", return_value=rows):
			c = invoice_print.invoice_containers("J-1")
		self.assertEqual((c.listed, c.more, c.summary), (["MSCU4821356 – 40' GP"], 0, ""))

		many = [frappe._dict(container_no=f"MSCU{i:07d}", size="40", container_type="GP", qty=1) for i in range(45)]
		many += [frappe._dict(container_no="", size="20", container_type="GP", qty=3)]
		with patch("frappe.get_all", return_value=many):
			c = invoice_print.invoice_containers("J-1")
		self.assertEqual(len(c.listed), invoice_print.MAX_LISTED_CONTAINERS)
		self.assertEqual(c.more, 46 - invoice_print.MAX_LISTED_CONTAINERS)
		self.assertEqual(c.summary, "45 × 40' GP, 3 × 20' GP")

	def test_air_job_prints_the_flight(self):
		job = frappe._dict(name="J-1", mode_of_shipment="Air", flight_number="SV 123", vessel_name="X")
		with patch("frappe.get_all", return_value=[]):
			s = invoice_print.invoice_shipment(job)
		self.assertEqual((s.is_air, s.carrier), (True, "SV 123"))

	def test_renders_shipment_and_stamp(self):
		si = make_invoice()
		shipment = frappe._dict(
			is_air=False,
			carrier="MSC AURORA / 245E",
			pol="Shanghai Port (CNSHA)",
			pod="Jeddah Islamic Port (SAJED)",
			containers=frappe._dict(listed=["MSCU4821356 – 40' GP"], more=0, summary=""),
		)
		with patch.object(invoice_print, "invoice_shipment", return_value=shipment), patch.object(
			invoice_print, "company_stamp", return_value="/files/stamp.png"
		):
			html = frappe.get_print("Sales Invoice", si.name, "Bilingual Tax Invoice", doc=si, no_letterhead=1)
		for text in (
			"Shipment Details", "MSC AURORA / 245E", "Shanghai Port (CNSHA)", "Jeddah Islamic Port (SAJED)",
			"MSCU4821356 – 40' GP", "Containers (1)", "/files/stamp.png",
		):
			self.assertIn(text, html)

	def test_no_shipment_box_without_a_job(self):
		html = frappe.get_print("Sales Invoice", "x", "Bilingual Tax Invoice", doc=make_invoice(), no_letterhead=1)
		self.assertNotIn("Shipment Details", html)


class TestLetterHead(IntegrationTestCase):
	"""Our custom formats print the Letter Head in place of their own header."""

	def setUp(self):
		self.lh = frappe.get_doc(
			{
				"doctype": "Letter Head",
				"letter_head_name": "_Test OFS Letter Head",
				"source": "HTML",
				"content": "<div>LH-TOP {{ letterhead_company(doc).name }}</div>",
				"footer_source": "HTML",
				"footer": "<div>LH-FOOT</div>",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.delete_doc("Letter Head", self.lh.name, force=True, ignore_permissions=True)

	def test_formats_use_the_letter_head(self):
		cases = (
			("Sales Invoice", make_invoice(), "Bilingual Tax Invoice"),
			("Operations", make_job(), "Proof of Delivery"),
			("Operations", make_job(), "Arrival Notice"),
		)
		for doctype, doc, fmt in cases:
			html = frappe.get_print(doctype, doc.name, fmt, doc=doc, letterhead=self.lh.name)
			self.assertIn("LH-TOP " + frappe.db.get_value("Company", company(), "company_name"), html, fmt)
			self.assertIn('id="footer-html"', html, fmt)
			self.assertIn("LH-FOOT", html, fmt)
			self.assertNotIn('class="hdr"', html, fmt)

	def test_built_header_without_letter_head(self):
		html = frappe.get_print("Operations", "J-TEST-POD-0001", "Proof of Delivery", doc=make_job(), no_letterhead=1)
		self.assertIn('class="hdr"', html)
		self.assertNotIn("LH-FOOT", html)

	def test_statement_letterhead(self):
		from forwarding import print_letterhead

		frappe.db.set_value("Company", company(), "default_letter_head", self.lh.name)
		lh = print_letterhead.company_letterhead(company())
		self.assertIn("LH-TOP", lh.header)
		self.assertIn("LH-FOOT", lh.footer)
