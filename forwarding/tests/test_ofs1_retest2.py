# Copyright (c) 2026, DVNKS Systems and contributors
"""Simran's ONE Freight retest (3 Nov): the Proof of Delivery's consignee,
address and port names, the Submit message, and the data patch. Everything is
rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.patches.v1_0 import ofs1_customer_connections, ofs1_retest2
from forwarding.pod_print import get_pod_context, port_label
from forwarding.tests.test_customer_360 import make_customer
from forwarding.tests.test_job_360 import make
from forwarding.tests.test_ofs1_prints import PrintCase, _render
from forwarding.transport_print import get_transport_order_context


def port(code, name, mode):
	key = f"{code}-{name}"
	if not frappe.db.exists("Port", key):
		frappe.get_doc({"doctype": "Port", "port_code": code, "port_name": name, "mode_of_shipment": mode}).insert(
			ignore_permissions=True
		)
	return key


class TestPortNames(PrintCase):
	def test_sea_port_reads_name_port_code(self):
		self.assertEqual(port_label(port("ZZDMM", "Test Dammam", "Sea")), "Test Dammam Port (ZZDMM)")

	def test_airport_and_names_that_already_say_so(self):
		self.assertEqual(port_label(port("ZZR", "Test Riyadh", "Air")), "Test Riyadh Airport (ZZR)")
		self.assertEqual(port_label(port("ZZJ", "Test Islamic Port", "Sea")), "Test Islamic Port (ZZJ)")

	def test_not_a_port_record_prints_as_typed(self):
		self.assertEqual((port_label("- Somewhere"), port_label(None)), ("Somewhere", ""))


class TestProofOfDelivery(PrintCase):
	def test_consignee_address_and_port(self):
		customer = make_customer(customer_name="Al Noor Test Co.", cr_no="1010101010")
		job = make(customer=customer.name)
		frappe.db.set_value("Operations", job.name, {"consignee": "", "port_of_destination": port("ZZDMM", "Test Dammam", "Sea")})
		job = frappe.get_doc("Operations", job.name)
		vehicle, driver = self.fleet()
		transport = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		from forwarding.api.service_status import set_status

		set_status("Transportation", transport.name, "In Transit", {"vehicle": vehicle, "driver": driver})
		set_status(
			"Transportation", transport.name, "Delivered", {"destination_location_address": "2nd Industrial City, Street 41\nRiyadh 14334"}
		)
		c = get_pod_context(job)
		self.assertEqual(c.consignee, "Al Noor Test Co.")
		self.assertEqual(c.delivery_address, "2nd Industrial City, Street 41, Riyadh 14334")
		self.assertEqual(c.port, "Test Dammam Port (ZZDMM)")
		text = _render("Proof of Delivery", job)
		self.assertIn("Test Dammam Port (ZZDMM)", text)
		self.assertIn("Al Noor Test Co.", text)
		self.assertEqual(get_transport_order_context(frappe.get_doc("Transportation", transport.name)).port, c.port)


class TestSubmitMessage(PrintCase):
	def test_port_is_required(self):
		job = make()
		job.mode_of_shipment = "Sea"
		job.port_of_loading = job.port_of_destination = None
		with patch("forwarding.job_rules.mode_of", return_value="Sea"):
			self.assertEqual(job.missing_ports(), ["Port of Loading is required", "Port of Discharge is required"])


class TestRetestPatch(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = frappe.db.get_value("Company", {}, "name")

	def run_patch(self):
		with patch.object(ofs1_retest2, "COMPANY", self.company):
			ofs1_retest2.execute()

	def test_skips_other_sites(self):
		before = frappe.db.count("Vehicle")
		with patch.object(ofs1_retest2, "COMPANY", "No Such Company"):
			ofs1_retest2.execute()
		self.assertEqual(frappe.db.count("Vehicle"), before)

	def test_data(self):
		if not frappe.db.exists("Shipment Type", "Saber Registration"):
			frappe.get_doc({"doctype": "Shipment Type", "shipment_type": "Saber Registration"}).insert(ignore_permissions=True)
		customer = make_customer(customer_name=ofs1_retest2.CUSTOMER, cr_no="1010101010")
		self.run_patch()
		self.run_patch()  # twice: nothing doubles
		# Gone, or disabled where a record uses it.
		self.assertIn(frappe.db.get_value("Shipment Type", "Saber Registration", "disabled"), (None, 1))
		self.assertFalse(frappe.db.exists("Customer", customer.name))
		self.assertEqual(frappe.get_meta("Customer").get_field("credit_period").default, "30 Days")
		self.assertTrue(frappe.db.exists("Vehicle", ofs1_retest2.SAMPLE_PLATE))
		self.assertEqual(frappe.db.count("Driver", {"full_name": ofs1_retest2.SAMPLE_DRIVER}), 1)

	def test_customer_with_a_job_is_kept(self):
		customer = make_customer(customer_name=ofs1_retest2.CUSTOMER, cr_no="1010101010")
		make(customer=customer.name)
		self.run_patch()
		self.assertTrue(frappe.db.exists("Customer", customer.name))


class TestCustomerConnections(IntegrationTestCase):
	def test_jobs_and_invoices(self):
		ofs1_customer_connections.execute()
		ofs1_customer_connections.execute()
		links = {(l.link_doctype, l.link_fieldname): l.group for l in frappe.get_meta("Customer").links}
		self.assertEqual(links[("Operations", "customer")], "Jobs")
		self.assertEqual(links[("Sales Invoice", "customer")], "Invoices")
		self.assertEqual(frappe.db.count("DocType Link", {"parent": "Customer", "link_doctype": "Operations"}), 1)
