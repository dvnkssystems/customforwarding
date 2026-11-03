# Copyright (c) 2026, DVNKS Systems and contributors
"""Simran's ONE Freight retest, second round (3 Nov): the test records and job
numbering, the port's name, and the driver's name on a Transportation.
Everything is rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.patches.v1_0 import ofs1_retest3, transport_driver_name
from forwarding.tests.test_customer_360 import make_customer
from forwarding.tests.test_job_360 import make
from forwarding.tests.test_supplier_fleet import make_driver


class Case(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.company = frappe.db.get_value("Company", {}, "name")

	def run_patch(self):
		with patch.object(ofs1_retest3, "COMPANY", self.company):
			ofs1_retest3.execute()


class TestCleanUp(Case):
	def test_test_customer_and_everything_of_it_go(self):
		customer = make_customer(customer_name=ofs1_retest3.CUSTOMER, cr_no="1010101010")
		job = make(customer=customer.name)
		transport = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		self.run_patch()
		for doctype, name in (("Transportation", transport.name), ("Operations", job.name), ("Customer", customer.name)):
			self.assertFalse(frappe.db.exists(doctype, name), f"{doctype} {name} left")

	def test_skips_other_sites(self):
		customer = make_customer(customer_name=ofs1_retest3.CUSTOMER, cr_no="1010101010")
		with patch.object(ofs1_retest3, "COMPANY", "No Such Company"):
			ofs1_retest3.execute()
		self.assertTrue(frappe.db.exists("Customer", customer.name))


class TestJobNumbering(Case):
	def test_counter_back_to_the_highest_number_in_use(self):
		highest = 0
		for doctype, digits in ofs1_retest3.counted_by_blank_series().items():
			for name in frappe.get_all(doctype, pluck="name"):
				if str(name)[-digits:].isdigit():
					highest = max(highest, int(str(name)[-digits:]))
		frappe.db.sql("update `tabSeries` set current = %s where name = ''", highest + 50)
		ofs1_retest3.reset_job_counter()
		self.assertEqual(frappe.db.sql("select current from `tabSeries` where name = ''")[0][0], highest)

	def test_never_raised(self):
		frappe.db.sql("update `tabSeries` set current = 0 where name = ''")
		ofs1_retest3.reset_job_counter()
		self.assertEqual(frappe.db.sql("select current from `tabSeries` where name = ''")[0][0], 0)

	def test_operations_shares_the_blank_counter(self):
		self.assertIn("Operations", ofs1_retest3.counted_by_blank_series())


class TestPort(Case):
	def test_renamed_with_links(self):
		if not frappe.db.exists("Port", ofs1_retest3.PORT_FROM):
			frappe.get_doc(
				{"doctype": "Port", "port_code": "SAJED", "port_name": "Jeddah islamic port", "mode_of_shipment": "Sea"}
			).insert(ignore_permissions=True)
		job = make(mode_of_shipment="Sea", port_of_loading="CNSHA-SHANGHAI", port_of_destination=ofs1_retest3.PORT_FROM)
		self.run_patch()
		target = "SAJED-Jeddah Islamic Port"
		self.assertEqual(frappe.db.get_value("Port", target, "port_name"), "Jeddah Islamic Port")
		self.assertEqual(frappe.db.get_value("Operations", job.name, "port_of_destination"), target)


class TestDriverName(Case):
	def test_fetched_and_backfilled(self):
		driver = make_driver(None, None)
		full_name = frappe.db.get_value("Driver", driver.name, "full_name")
		transport = frappe.get_doc({"doctype": "Transportation", "operations": make().name, "driver": driver.name}).insert(
			ignore_permissions=True
		)
		self.assertEqual(transport.driver_name, full_name)
		frappe.db.set_value("Transportation", transport.name, "driver_name", "")
		transport_driver_name.execute()
		self.assertEqual(frappe.db.get_value("Transportation", transport.name, "driver_name"), full_name)
