# Copyright (c) 2026, DVNKS Systems and contributors
"""Simran's ONE Freight review (2 Nov), the prints: buyer VAT on the tax
invoice (item 12), the seller's VAT and CR lines (13), the Proof of Delivery's
columns, delivery time, driver and truck (14), Job Delivery Note off (15) and
the Transport Order on a Transportation (17). Everything is rolled back."""

import re
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.api.service_status import set_status
from forwarding.invoice_print import get_tax_invoice_context
from forwarding.patches.v1_0 import ofs1_prints
from forwarding.pod_print import get_pod_context
from forwarding.tests.test_customer_360 import make_customer
from forwarding.tests.test_job_360 import make
from forwarding.tests.test_supplier_fleet import make_driver, make_vehicle
from forwarding.transport_print import get_transport_order_context

VAT = "300000000000003"
CR = "1010101010"


def _text(html):
	return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _render(print_format, doc):
	return _text(frappe.render_template(frappe.db.get_value("Print Format", print_format, "html"), {"doc": doc}))


class PrintCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.company = frappe.db.get_value("Company", {}, "name")

	def fleet(self):
		return make_vehicle(None, None).name, make_driver(None, None).name

	def delivered_transport(self, job, **values):
		vehicle, driver = self.fleet()
		transport = frappe.get_doc({"doctype": "Transportation", "operations": job.name, **values}).insert(
			ignore_permissions=True
		)
		set_status("Transportation", transport.name, "In Transit", {"vehicle": vehicle, "driver": driver})
		set_status("Transportation", transport.name, "Delivered", {"destination_location_address": "Warehouse 4, Riyadh"})
		return frappe.get_doc("Transportation", transport.name)


class TestTaxInvoice(PrintCase):
	def invoice(self, customer):
		doc = frappe.new_doc("Sales Invoice")
		doc.update({"company": self.company, "customer": customer, "currency": "SAR", "posting_date": frappe.utils.nowdate()})
		doc.update({"total": 0, "net_total": 0, "grand_total": 0, "total_taxes_and_charges": 0})
		return doc

	# Item 12: the customer form's VAT Registration Number is printed as the buyer's VAT.
	def test_buyer_vat_from_the_vat_registration_number(self):
		customer = make_customer(tax_id=None, custom_vat_registration_number=VAT, cr_no=CR)
		self.assertEqual(get_tax_invoice_context(self.invoice(customer.name)).buyer.tax_id, VAT)

	def test_tax_id_still_comes_first(self):
		customer = make_customer(tax_id="311111111111113", custom_vat_registration_number=VAT, cr_no=CR)
		self.assertEqual(get_tax_invoice_context(self.invoice(customer.name)).buyer.tax_id, "311111111111113")

	# Item 13: VAT No. and C.R. No. lines under the seller, "-" until filled in.
	def test_seller_vat_and_cr_lines_always_print(self):
		customer = make_customer(custom_vat_registration_number=VAT, cr_no=CR)
		frappe.db.set_value("Company", self.company, {"tax_id": "", "cr_number": ""})
		text = _render("Bilingual Tax Invoice", self.invoice(customer.name))
		self.assertIn("VAT No.: -", text)
		self.assertIn("C.R. No.: -", text)
		self.assertIn("السجل التجاري: -", text)
		frappe.db.set_value("Company", self.company, {"tax_id": "399999999900003", "cr_number": "1010101010"})
		text = _render("Bilingual Tax Invoice", self.invoice(customer.name))
		self.assertIn("VAT No.: 399999999900003", text)
		self.assertIn("C.R. No.: 1010101010", text)


class TestProofOfDelivery(PrintCase):
	# Item 14.
	def test_delivery_time_driver_and_truck_from_the_transportation(self):
		job = make()
		transport = self.delivered_transport(job)
		self.assertTrue(transport.delivery_time, "Mark Delivered stamps the time")
		c = get_pod_context(job)
		self.assertTrue(c.delivery_time)
		self.assertTrue(c.vehicle)
		self.assertTrue(c.driver)
		self.assertIn(c.delivery_time, _render("Proof of Delivery", job))

	def test_a_typed_delivery_time_is_kept(self):
		job = make()
		vehicle, driver = self.fleet()
		transport = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		set_status("Transportation", transport.name, "In Transit", {"vehicle": vehicle, "driver": driver})
		set_status(
			"Transportation",
			transport.name,
			"Delivered",
			{"destination_location_address": "Warehouse 4", "delivery_time": "09:15:00"},
		)
		self.assertEqual(get_pod_context(job).delivery_time, "09:15")

	def test_goods_from_the_transportations_containers_when_the_job_has_none(self):
		job = make()
		self.assertFalse(job.get("container_details"))
		self.delivered_transport(job, container_details=[{"container_no": "MSKU1234565", "seal_no": "S-9"}])
		c = get_pod_context(job)
		self.assertEqual((c.unit, [line.ref for line in c.lines]), ("containers", ["MSKU1234565"]))

	def test_every_goods_column_has_a_heading(self):
		job = make()
		html = frappe.render_template(frappe.db.get_value("Print Format", "Proof of Delivery", "html"), {"doc": job})
		head = html[html.index('<table class="lines">') : html.index("</thead>")]
		self.assertNotRegex(head, r"<th[^>]*>\s*</th>")

	# Item 15.
	def test_job_delivery_note_is_off(self):
		frappe.db.set_value("Print Format", "Job Delivery Note", "disabled", 0)
		ofs1_prints.execute()
		self.assertEqual(frappe.db.get_value("Print Format", "Job Delivery Note", "disabled"), 1)


class TestTransportOrder(PrintCase):
	# Item 17.
	def test_default_print_for_a_transportation(self):
		self.assertEqual(frappe.get_meta("Transportation").default_print_format, "Transport Order")

	def test_shows_route_truck_driver_and_no_amounts(self):
		job = make()
		transport = self.delivered_transport(
			job,
			departure_location="Dammam Port",
			destination_location="Customer warehouse",
			container_details=[{"container_no": "MSKU1234565"}],
			cost_table=[],
		)
		c = get_transport_order_context(transport)
		self.assertEqual((c.job_no, c.to_address), (job.name, ["Warehouse 4, Riyadh"]))
		self.assertTrue(c.vehicle and c.driver)
		text = _render("Transport Order", transport)
		for shown in ("TRANSPORT ORDER", job.name, "Dammam Port", "Customer warehouse", "MSKU1234565"):
			self.assertIn(shown, text)
		for hidden in ("Amount", "Account", "SAR", "Cost"):
			self.assertNotIn(hidden, text)
