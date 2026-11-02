# Copyright (c) 2026, DVNKS Systems and contributors
"""Simran's ONE Freight review (2 Nov): ports before a Sea / Air job is
submitted (item 6), a customer's branch, currency and CR No (2, 7), a foreign
invoice's exchange rate (9), what a transport needs to move on (16), a
deleted transport's charges leaving the job (19), the invoice settings
(3, 11), the "Job" label (18) and the clean-start patch. Everything is rolled
back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from forwarding.api import service_status
from forwarding.child_tables import remove_costs_from_job
from forwarding.invoice_currency import fill_exchange_rate
from forwarding.party_validation import ALL_BRANCHES, needs_cr_no
from forwarding.patches.v1_0 import ofs1_clean_start, ofs1_invoice_settings
from forwarding.tests.test_customer_360 import make_customer
from forwarding.tests.test_job_360 import make


class OfsCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.company = frappe.db.get_value("Company", {}, "name")
		self.home = frappe.get_cached_value("Company", self.company, "default_currency")


class TestJobPorts(OfsCase):
	# Item 6.
	def test_sea_and_air_jobs_need_both_ports(self):
		job = make(mode_of_shipment="Air", port_of_loading=None, port_of_destination=None)
		problems = job.missing_ports()
		self.assertEqual(len(problems), 2)
		self.assertTrue(all(p.startswith("Value missing for") for p in problems))
		self.assertTrue(any("Port of Loading" in p or "Port Of Loading" in p for p in problems))

	def test_land_jobs_need_no_port(self):
		job = make(mode_of_shipment="Air")
		job.mode_of_shipment = "Land"
		job.port_of_loading = job.port_of_destination = None
		self.assertEqual(job.missing_ports(), [])

	def test_submit_names_the_missing_ports(self):
		job = make(mode_of_shipment="Air", port_of_loading=None, port_of_destination=None)
		self.assertTrue(any(p in job.submit_problems() for p in job.missing_ports()))


class TestCustomerRules(OfsCase):
	# Items 2 and 7.
	def test_new_saudi_customer_needs_a_cr_no(self):
		with self.assertRaises(frappe.MandatoryError):
			make_customer(cr_no=None, country="Saudi Arabia")

	def test_customer_abroad_needs_none(self):
		other = frappe.db.get_value("Country", {"name": ["!=", "Saudi Arabia"]}, "name")
		customer = make_customer(cr_no=None, country=other)
		self.assertFalse(customer.cr_no)

	def test_old_customer_without_cr_saves_until_its_country_changes(self):
		other = frappe.db.get_value("Country", {"name": ["!=", "Saudi Arabia"]}, "name")
		customer = make_customer(cr_no=None, country=other)
		customer.customer_name = customer.customer_name + " edited"
		customer.save(ignore_permissions=True)
		customer.country = "Saudi Arabia"
		self.assertTrue(needs_cr_no(customer))

	def test_branch_all_is_refused_for_a_new_customer(self):
		if not frappe.db.exists("Branch", ALL_BRANCHES):
			self.skipTest("no ALL branch on this site")
		with self.assertRaises(frappe.ValidationError):
			make_customer(cr_no="1010999999", branch=ALL_BRANCHES)

	def test_customer_already_on_all_still_saves(self):
		if not frappe.db.exists("Branch", ALL_BRANCHES):
			self.skipTest("no ALL branch on this site")
		customer = make_customer(cr_no="1010999999")
		customer.db_set("branch", ALL_BRANCHES)
		customer.reload()
		customer.customer_name = customer.customer_name + " edited"
		customer.save(ignore_permissions=True)

	def test_new_customer_takes_the_company_currency(self):
		customer = make_customer(cr_no="1010999999", default_currency=None)
		self.assertEqual(customer.default_currency, self.home)


def invoice(**values):
	return frappe._dict(
		doctype="Sales Invoice",
		docstatus=0,
		company=frappe.db.get_value("Company", {}, "name"),
		customer=None,
		posting_date=nowdate(),
		meta=frappe.get_meta("Sales Invoice"),
		**values,
	)


class TestExchangeRate(OfsCase):
	# Item 9.
	def foreign(self):
		return "USD" if self.home != "USD" else "EUR"

	def test_foreign_currency_at_one_takes_the_days_rate(self):
		doc = invoice(currency=self.foreign(), conversion_rate=1)
		with patch("erpnext.setup.utils.get_exchange_rate", return_value=3.75):
			fill_exchange_rate(doc)
		self.assertEqual(doc.conversion_rate, 3.75)

	def test_no_rate_refuses_the_save(self):
		doc = invoice(currency=self.foreign(), conversion_rate=1)
		with patch("erpnext.setup.utils.get_exchange_rate", return_value=0):
			with self.assertRaises(frappe.MandatoryError):
				fill_exchange_rate(doc)

	def test_a_typed_rate_is_kept(self):
		doc = invoice(currency=self.foreign(), conversion_rate=3.7)
		with patch("erpnext.setup.utils.get_exchange_rate", return_value=3.75):
			fill_exchange_rate(doc)
		self.assertEqual(doc.conversion_rate, 3.7)

	def test_company_currency_is_one(self):
		doc = invoice(currency=None, conversion_rate=0)
		fill_exchange_rate(doc)
		self.assertEqual((doc.currency, doc.conversion_rate), (self.home, 1))


class TestTransportSteps(OfsCase):
	# Item 16.
	def test_steps_ask_for_vehicle_driver_and_address(self):
		flow = service_status.FLOWS["Transportation"]
		self.assertEqual(flow["needs"]["In Transit"], ["vehicle", "driver"])
		self.assertEqual(flow["needs"]["Delivered"], ["destination_location_address"])

	def test_start_transit_without_a_vehicle_is_refused(self):
		job = make()
		transport = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.MandatoryError):
			service_status.set_status("Transportation", transport.name, "In Transit")
		described = service_status.get_status("Transportation", transport.name)
		needs = {n["fieldname"]: n for n in described["next_needs"]}
		self.assertEqual(set(needs), {"vehicle", "driver"})
		self.assertEqual(needs["vehicle"]["options"], "Vehicle")

	def test_label_reads_job(self):
		for doctype in ("Transportation", "Custom Clearance"):
			self.assertEqual(frappe.get_meta(doctype).get_label("operations"), "Job")


class TestDeletedTransportCosts(OfsCase):
	# Item 19.
	def test_charges_it_added_leave_the_job(self):
		job = make()
		item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 0}, "name")
		if not item:
			self.skipTest("needs a service item")
		transport = frappe.get_doc(
			{"doctype": "Transportation", "operations": job.name, "cost_table": [{"item": item, "cost": 250}]}
		).insert(ignore_permissions=True)
		added = frappe.get_all("Cost Table", filters={"parent": job.name, "ref_docname": transport.name}, pluck="name")
		self.assertTrue(added)
		remove_costs_from_job(transport)
		self.assertFalse(frappe.get_all("Cost Table", filters={"parent": job.name, "ref_docname": transport.name}))


class TestInvoiceSettings(OfsCase):
	# Items 3, 7 and 11.
	def test_settings(self):
		ofs1_invoice_settings.execute()
		for doctype in ("Sales Invoice", "Purchase Invoice", "Purchase Invoice Item"):
			self.assertIn("is_group", frappe.get_meta(doctype).get_field("cost_center").link_filters or "")
		self.assertTrue(frappe.get_meta("Sales Invoice").get_field("apply_tds").hidden)
		self.assertEqual(frappe.get_meta("Customer").get_field("default_currency").default, self.home)


class TestCleanStart(OfsCase):
	def test_other_sites_skip_it(self):
		if frappe.db.exists("Company", ofs1_clean_start.COMPANY):
			self.skipTest("this is the ONE Freight site")
		with patch.object(ofs1_clean_start, "remove") as remove:
			ofs1_clean_start.execute()
		remove.assert_not_called()

	def test_removes_a_record_and_steps_its_series_back(self):
		frappe.db.sql("insert into `tabSeries` (name, current) values ('ZZOFS-', 7) on duplicate key update current = 7")
		ofs1_clean_start.step_back_series("ZZOFS-0007")
		self.assertEqual(frappe.db.sql("select current from `tabSeries` where name='ZZOFS-'")[0][0], 6)
		ofs1_clean_start.step_back_series("ZZOFS-0003")  # not the last: untouched
		self.assertEqual(frappe.db.sql("select current from `tabSeries` where name='ZZOFS-'")[0][0], 6)

	def test_a_record_still_in_use_is_kept(self):
		job = make()
		customer = job.customer
		ofs1_clean_start.remove("Customer", customer)
		self.assertTrue(frappe.db.exists("Customer", customer))
