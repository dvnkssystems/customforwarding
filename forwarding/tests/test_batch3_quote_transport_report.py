# Copyright (c) 2026, DVNKS Systems and contributors
"""Batch 3 (quote, transport and report), Simran's Round 3 retest: a
Transportation's Costs take only transport charges (item 11), the quote's
one mode and its Sea Shipment Type (12), accounts on a quote-made job's
estimate (13), a new customer's contact email (15), the report's job
statuses (18 / A-45) and "No costs yet" (19), and the RIYADH CITY port (20).
Uses the site's own masters; everything is rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.estimation import get_costed, job_figures, job_row, job_status
from forwarding.forwarding.doctype.operations.operations import (
	TRANSPORT_ITEM_GROUP,
	default_expense_account,
	is_transport_charge,
	make_transportaion,
)
from forwarding.patches.v1_0 import b3_riyadh_city_port, b3_transport_charges
from forwarding.quote_to_job import make_operations_from_quote
from forwarding.tests.test_customer_360 import make_quote
from forwarding.tests.test_job_360 import CUSTOMER, make
from forwarding.tests.test_r2_documents_dates import make_customer


class Batch3Case(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)


def transport_item():
	return next((i for i in b3_transport_charges.TRANSPORT_ITEMS if frappe.db.exists("Item", i)), None)


def other_item():
	return frappe.db.get_value(
		"Item", {"item_group": ["!=", TRANSPORT_ITEM_GROUP], "disabled": 0, "is_stock_item": 0}, "name"
	)


class TestTransportCosts(Batch3Case):
	# Item 11.
	def setUp(self):
		super().setUp()
		b3_transport_charges.execute()
		self.transport, self.other = transport_item(), other_item()
		if not (self.transport and self.other):
			self.skipTest("needs a transport item and another service item")

	def test_patch_moves_the_items_into_the_group(self):
		self.assertTrue(frappe.db.exists("Item Group", TRANSPORT_ITEM_GROUP))
		for item in b3_transport_charges.TRANSPORT_ITEMS:
			if frappe.db.exists("Item", item):
				self.assertEqual(frappe.db.get_value("Item", item, "item_group"), TRANSPORT_ITEM_GROUP)
		self.assertTrue(is_transport_charge(self.transport))
		self.assertFalse(is_transport_charge(self.other))
		self.assertFalse(is_transport_charge(None))

	def test_transportation_takes_only_transport_charges(self):
		job = make()
		job.append("cost_table", {"item": self.other, "rate": 150, "cost": 100})
		job.append("cost_table", {"item": self.transport, "rate": 800, "cost": 600})
		job.append("cost_table", {"item_name": "Free text", "rate": 50, "cost": 10})
		job.save(ignore_permissions=True)

		transport = make_transportaion(job.name)
		self.assertEqual([r.item for r in transport.cost_table], [self.transport])
		self.assertEqual((transport.cost_table[0].rate, transport.cost_table[0].cost), (800, 600))


class TestQuoteMode(Batch3Case):
	# Item 12.
	def test_one_mode_on_the_quote(self):
		meta = frappe.get_meta("Quote")
		self.assertTrue(meta.get_field("mode").hidden)
		self.assertIn("doc.mode_of_shipment", meta.get_field("sea_shipment_type").depends_on)

	def test_sea_shipment_type_reaches_the_job(self):
		item = other_item()
		if not (item and frappe.db.exists("Shipment Type", "FCL") and frappe.db.exists("Mode Of Shipment", "Sea")):
			self.skipTest("needs an Item, Shipment Type FCL and Mode Sea")
		quote = make_quote(
			CUSTOMER,
			validity_in_days=10,
			mode=None,
			mode_of_shipment="Sea",
			sea_shipment_type="FCL",
			items=[{"item": item, "rate": 100, "units": 1}],
		)
		self.assertEqual(quote.mode, "SEA")
		quote.submit()
		job = make_operations_from_quote(quote.name)
		self.assertEqual((job.mode_of_shipment, job.shipment_type), ("Sea", "FCL"))


class TestQuoteRowsAndAccounts(Batch3Case):
	# Item 13.
	def test_a_row_without_item_is_refused_naming_the_row(self):
		item = other_item()
		with self.assertRaises(frappe.MandatoryError) as raised:
			make_quote(
				CUSTOMER,
				validity_in_days=10,
				items=[{"item": item, "rate": 100, "units": 1}, {"description": "Handling", "rate": 50, "units": 1}],
			)
		self.assertIn("row 2", str(raised.exception))

	def test_job_from_quote_opens_with_accounts(self):
		item = other_item()
		if not item:
			self.skipTest("needs an Item")
		quote = make_quote(CUSTOMER, validity_in_days=10, items=[{"item": item, "rate": 100, "units": 1}])
		quote.submit()
		job = make_operations_from_quote(quote.name)
		expected = default_expense_account(item, job.company)
		if not expected:
			self.skipTest("no expense account for the item on this site")
		self.assertEqual([r.account for r in job.cost_table], [expected])


class TestCustomerContactEmail(Batch3Case):
	# Item 15.
	def test_email_on_create_makes_the_primary_contact(self):
		customer = make_customer(contact_email="b3.contact@example.com")
		customer.reload()
		self.assertEqual(customer.email_id, "b3.contact@example.com")
		self.assertTrue(customer.customer_primary_contact)
		self.assertEqual(
			frappe.db.get_value("Contact", customer.customer_primary_contact, "email_id"), "b3.contact@example.com"
		)

	def test_no_email_is_fine(self):
		customer = make_customer()
		self.assertFalse(customer.get("email_id"))

	def test_a_bad_email_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_customer(contact_email="not-an-email")


def job(docstatus, status="Open"):
	return frappe._dict(name="J", date=None, customer=None, branch=None, mode_of_shipment=None, docstatus=docstatus, operations_status=status)


class TestEstimationStatuses(Batch3Case):
	# Item 18 / A-45: the Jobs list's statuses.
	def test_status_rule(self):
		self.assertEqual(
			[
				job_status(job(0)),
				job_status(job(1)),
				job_status(job(1, "On Hold")),
				job_status(job(1, "Closed")),
				job_status(job(2)),
				job_status(job(0, "Cancelled")),
				job_status(job(1, "Ops Completed")),
				job_status(job(1, "")),
			],
			["Draft", "Submitted", "On Hold", "Closed", "Cancelled", "Cancelled", "Ops Completed", "Submitted"],
		)

	def test_report_row_for_a_draft_job(self):
		self.assertEqual(job_figures(make().name)["status"], "Draft")


class TestNoCostsYet(Batch3Case):
	# Item 19.
	def test_income_without_a_bill_has_no_variance(self):
		row = job_row(job(1), {"income": 100, "expense": 50}, {"income": 150}, has_costs=False)
		self.assertEqual((row["variance_label"], row["variance_pct"], row["has_costs"]), ("No costs yet", None, 0))

	def test_with_a_bill_the_variance_shows(self):
		row = job_row(job(1), {"income": 100, "expense": 50}, {"income": 150, "expense": 60}, has_costs=True)
		self.assertIsNone(row["variance_label"])
		self.assertEqual((row["variance"], row["variance_pct"]), (40, 80))

	def test_not_billed_comes_first(self):
		row = job_row(job(1), {"income": 100}, {"expense": 60}, has_costs=False)
		self.assertEqual(row["variance_label"], "Not billed yet")

	def test_costed_means_a_submitted_purchase_invoice(self):
		billed = frappe.db.get_value("Purchase Invoice", {"docstatus": 1, "operations": ["is", "set"]}, "operations")
		draft_job = make().name
		names = [draft_job] + ([billed] if billed else [])
		costed = get_costed(names)
		self.assertNotIn(draft_job, costed)
		if billed:
			self.assertIn(billed, costed)


class TestRiyadhCityPort(Batch3Case):
	# Item 20.
	def test_old_record_is_renamed_and_its_jobs_follow(self):
		old = b3_riyadh_city_port.OLD
		if not frappe.db.exists("Port", old):
			port = frappe.get_doc(
				{"doctype": "Port", "port_name": "RIYADH CITY", "country": "Saudi Arabia", "mode_of_shipment": "Land"}
			)
			port.insert(ignore_permissions=True, set_name=old)
		job_name = make(mode_of_shipment="Land", port_of_destination=old).name

		b3_riyadh_city_port.execute()
		self.assertFalse(frappe.db.exists("Port", old))
		self.assertEqual(frappe.db.get_value("Port", b3_riyadh_city_port.NEW, "port_code"), b3_riyadh_city_port.CODE)
		self.assertEqual(frappe.db.get_value("Operations", job_name, "port_of_destination"), b3_riyadh_city_port.NEW)

		b3_riyadh_city_port.execute()  # nothing left to do
