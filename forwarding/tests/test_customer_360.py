# Copyright (c) 2026, DVNKS Systems and contributors
"""Customer 360: payload shape, KPIs, banners C1-C3, the permission gate and
cache invalidation.

Each test makes its own customer so the numbers are its own; it uses the
site's company, item and accounts (like test_job_360) and everything is
rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import customer_banners
from forwarding.api import customer_360
from forwarding.job_events import customer_cache_key
from forwarding.tests.test_job_360 import ITEM, _first, make, make_payment

NO_ROLE_USER = "customer360-norole@example.com"


def make_customer(**values):
	company = customer_360.default_company()
	# The company has no default receivable account; the demo customers each
	# carry one, so borrow theirs.
	receivable = _first("Party Account", {"parenttype": "Customer", "company": company})
	receivable = frappe.db.get_value("Party Account", receivable, "account")
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"C360 Test {frappe.generate_hash(length=6)}",
			"customer_type": "Company",
			"customer_group": _first("Customer Group", {"is_group": 0}),
			"territory": _first("Territory", {"is_group": 0}),
			# Mandatory on this site (Property Setter / Custom Field).
			"branch": _first("Branch"),
			"default_currency": frappe.get_cached_value("Company", company, "default_currency"),
			"accounts": [{"company": company, "account": receivable}],
			**values,
		}
	).insert(ignore_permissions=True)


def make_invoice(customer, amount, due_in_days=0, job=None, submit=True):
	"""A Sales Invoice due due_in_days from today (negative: already overdue)."""
	due = add_days(nowdate(), due_in_days)
	posting = min(nowdate(), due)
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": customer_360.default_company(),
			"customer": customer,
			"operations": job,
			"posting_date": posting,
			"due_date": due,
			"set_posting_time": 1,
			"items": [{"item_code": ITEM, "qty": 1, "rate": amount}],
		}
	)
	si.insert(ignore_permissions=True)
	if submit:
		si.submit()
	return si


def make_quote(customer, validity_in_days=None, **values):
	return frappe.get_doc(
		{
			"doctype": "Quote",
			"consignee": customer,
			"date": nowdate(),
			"validity": add_days(nowdate(), validity_in_days) if validity_in_days is not None else None,
			"mode": "SEA",
			**values,
		}
	).insert(ignore_permissions=True)


def fresh(customer):
	frappe.cache.delete_value(customer_cache_key(customer))
	return customer_360.get(customer)


def is_cached(customer):
	return frappe.cache.get_value(customer_cache_key(customer)) is not None


def codes(payload):
	return [b["code"] for b in payload["banners"]]


class TestCustomer360(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Production-copied sites carry Server Scripts on Sales Invoice that
		# raise when server scripts are disabled; not what is under test.
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.customer = make_customer(cr_no="1010999999", custom_vat_registration_number="300000000000003")

	def test_shape(self):
		job = make(customer=self.customer.name)
		make_invoice(self.customer.name, 500, job=job.name)
		make_quote(self.customer.name, 10)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Rana",
				"email_ids": [{"email_id": "rana.c360@example.com", "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": self.customer.name}],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "HQ",
				"address_type": "Billing",
				"address_line1": "King Fahd Road",
				"city": "Riyadh",
				"country": "Saudi Arabia",
				"links": [{"link_doctype": "Customer", "link_name": self.customer.name}],
			}
		).insert(ignore_permissions=True)

		data = fresh(self.customer.name)
		self.assertEqual(
			set(data),
			{
				"currency", "customer", "kpis", "banners", "jobs", "quotes", "invoices", "payments",
				"documents", "contacts", "addresses",
			},
		)
		self.assertEqual(
			set(data["customer"]),
			{
				"name", "customer_name", "customer_group", "territory", "tax_id", "cr_no", "disabled",
				"customer_group_parent", "status", "salesman", "default_salesman", "branch", "credit_limit",
				"primary_contact",
				"primary_address",
			},
		)
		self.assertEqual(
			set(data["kpis"]),
			{
				"active_jobs", "open_quotes", "outstanding", "overdue", "credit_used", "credit_limit",
				"credit_pct", "documents_on_file", "documents_total",
			},
		)
		c = data["customer"]
		self.assertEqual(c["cr_no"], "1010999999")
		self.assertEqual(c["tax_id"], "300000000000003", "falls back to the KSA VAT number")
		self.assertEqual(c["status"], "Active")
		self.assertEqual(c["primary_contact"]["name"], contact.name)
		self.assertEqual(c["primary_contact"]["email_id"], "rana.c360@example.com")
		self.assertIn("King Fahd Road", c["primary_address"]["address_display"])

		self.assertEqual([j["name"] for j in data["jobs"]], [job.name])
		self.assertEqual(
			set(data["jobs"][0]),
			{
				"name", "operations_status", "billing_status", "mode_of_shipment", "job_type",
				"port_of_loading", "port_of_destination", "etd_date", "eta_date", "date", "docstatus",
			},
		)
		self.assertEqual(data["quotes"][0]["status"], "Open")
		self.assertEqual(
			set(data["quotes"][0]), {"name", "date", "validity", "mode", "pol", "pod", "total", "status"}
		)
		inv = data["invoices"][0]
		self.assertEqual(inv["operations"], job.name)
		self.assertIs(inv["overdue"], False)
		self.assertEqual(len(data["contacts"]), 1)
		self.assertEqual(data["addresses"][0]["city"], "Riyadh")
		# The response is plain JSON (dates as strings).
		self.assertIsInstance(inv["posting_date"], str)

	def test_status_and_salesman(self):
		self.customer.db_set("is_blocked", 1)
		self.assertEqual(fresh(self.customer.name)["customer"]["status"], "Blocked")
		self.customer.db_set("disabled", 1)
		self.assertEqual(fresh(self.customer.name)["customer"]["status"], "Disabled")

		sales_person = frappe.db.get_value("Sales Person", {"is_group": 0}, "name")
		if sales_person:
			make(customer=self.customer.name, salesman=sales_person)
			self.assertEqual(fresh(self.customer.name)["customer"]["salesman"], sales_person)

	def test_kpis_outstanding_overdue_credit(self):
		job = make(customer=self.customer.name)
		make(customer=self.customer.name, operations_status="Closed")
		current = make_invoice(self.customer.name, 1000, due_in_days=15, job=job.name)
		late = make_invoice(self.customer.name, 400, due_in_days=-10)
		make_invoice(self.customer.name, 9999, submit=False)  # drafts do not count

		k = fresh(self.customer.name)["kpis"]
		self.assertEqual(k["active_jobs"], 1, "the closed job is not active")
		owed = current.outstanding_amount + late.outstanding_amount
		self.assertEqual(k["outstanding"], owed)
		self.assertEqual(k["overdue"], late.outstanding_amount)
		self.assertEqual(k["credit_used"], owed)
		self.assertIsNone(k["credit_pct"], "no limit, no percentage")

		make_payment(late, late.outstanding_amount)
		k = fresh(self.customer.name)["kpis"]
		self.assertEqual(k["outstanding"], current.outstanding_amount)
		self.assertEqual(k["overdue"], 0)

		# ERPNext's Customer Credit Limit row wins over the Freight Settings field.
		self.customer.reload()
		self.customer.credit_limit_flcs = 1
		self.customer.append(
			"credit_limits", {"company": customer_360.default_company(), "credit_limit": 4000}
		)
		self.customer.save(ignore_permissions=True)
		k = fresh(self.customer.name)["kpis"]
		self.assertEqual(k["credit_limit"], 4000)
		self.assertEqual(k["credit_pct"], round(current.outstanding_amount / 4000 * 100, 2))

	def test_documents_on_file(self):
		docs = frappe.get_all("Document List", limit=2, pluck="name", order_by="name")
		if len(docs) < 2:
			self.skipTest("needs two Document List records")
		job = make(
			customer=self.customer.name,
			document_table=[
				{"document": docs[0], "stage": "Documentation", "received": "Yes"},
				{"document": docs[1], "stage": "Arrival", "received": "No"},
			],
		)
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "c360-cr.txt",
				"content": b"CR copy",
				"attached_to_doctype": "Customer",
				"attached_to_name": self.customer.name,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)

		data = fresh(self.customer.name)
		self.assertEqual(data["kpis"]["documents_on_file"], 2, "one received job document + one file")
		sources = {(d["source_doctype"], d["source_name"]) for d in data["documents"]}
		self.assertEqual(sources, {("Operations", job.name), ("Customer", self.customer.name)})

	def test_banner_c1_over_credit_limit(self):
		make_invoice(self.customer.name, 1500, due_in_days=30)
		self.assertNotIn("C1", codes(fresh(self.customer.name)))

		self.customer.db_set("credit_limit_flcs", 1000)
		data = fresh(self.customer.name)
		self.assertIn("C1", codes(data))
		c1 = next(b for b in data["banners"] if b["code"] == "C1")
		self.assertEqual((c1["colour"], c1["action"]), ("critical", "view_invoices"))
		self.assertGreater(data["kpis"]["credit_pct"], 100)

	def test_banner_c2_overdue_invoices(self):
		make_invoice(self.customer.name, 300, due_in_days=5)
		self.assertNotIn("C2", codes(fresh(self.customer.name)))

		first = make_invoice(self.customer.name, 200, due_in_days=-3)
		make_invoice(self.customer.name, 100, due_in_days=-1)
		data = fresh(self.customer.name)
		c2 = next(b for b in data["banners"] if b["code"] == "C2")
		self.assertEqual((c2["colour"], c2["action"]), ("critical", "view_invoices"))
		self.assertTrue(c2["message"].startswith("2 invoices overdue"))
		self.assertIn(customer_banners.format_date(first.due_date), c2["message"])
		self.assertEqual(sum(1 for i in data["invoices"] if i["overdue"]), 2)

	def test_banner_c3_quote_expiring(self):
		make_quote(self.customer.name, 10)
		make_quote(self.customer.name, -1)
		make_quote(self.customer.name)  # no validity: open, never expiring
		data = fresh(self.customer.name)
		self.assertNotIn("C3", codes(data))
		self.assertEqual(data["kpis"]["open_quotes"], 2)
		self.assertEqual(sorted(q["status"] for q in data["quotes"]), ["Expired", "Open", "Open"])

		soon = make_quote(self.customer.name, 2)
		data = fresh(self.customer.name)
		c3 = next(b for b in data["banners"] if b["code"] == "C3")
		self.assertEqual((c3["colour"], c3["action"]), ("warning", "view_quotes"))
		self.assertIn(soon.name, c3["message"])

	def test_permission(self):
		if not frappe.db.exists("User", NO_ROLE_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": NO_ROLE_USER,
					"first_name": "No Role",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(NO_ROLE_USER)
		self.assertRaises(frappe.PermissionError, customer_360.get, self.customer.name)

	def test_lists_hidden_without_doctype_read(self):
		make_invoice(self.customer.name, 100, due_in_days=5)
		fresh(self.customer.name)
		with patch.object(
			frappe, "has_permission", side_effect=lambda doctype, *a, **kw: doctype != "Sales Invoice"
		):
			data = customer_360.get(self.customer.name)
		self.assertEqual(data["invoices"], [])
		self.assertEqual(data["kpis"]["outstanding"], 100)

	def test_cache_invalidation(self):
		name = self.customer.name

		def assert_cleared(action, label):
			customer_360.get(name)
			self.assertTrue(is_cached(name))
			action()
			self.assertFalse(is_cached(name), f"{label} should drop the cache")

		job = make(customer=name)
		assert_cleared(lambda: job.save(ignore_permissions=True), "job save")
		si = make_invoice(name, 100, submit=False)
		assert_cleared(si.submit, "invoice submit")
		si.reload()
		assert_cleared(lambda: make_payment(si, 50), "payment submit")
		quote = make_quote(name, 10)
		assert_cleared(lambda: quote.save(ignore_permissions=True), "quote save")
		assert_cleared(lambda: self.customer.save(ignore_permissions=True), "customer save")
		assert_cleared(
			lambda: frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Cache",
					"links": [{"link_doctype": "Customer", "link_name": name}],
				}
			).insert(ignore_permissions=True),
			"contact insert",
		)
		assert_cleared(
			lambda: frappe.get_doc(
				{
					"doctype": "File",
					"file_name": "c360-cache.txt",
					"content": b"x",
					"attached_to_doctype": "Customer",
					"attached_to_name": name,
					"is_private": 1,
				}
			).insert(ignore_permissions=True),
			"file attach",
		)
		assert_cleared(lambda: frappe.delete_doc("Quote", quote.name, ignore_permissions=True), "quote delete")

	def test_cached_for_a_minute(self):
		fresh(self.customer.name)
		self.assertTrue(is_cached(self.customer.name))
		with patch.object(customer_360, "build", side_effect=AssertionError("should be cached")):
			customer_360.get(self.customer.name)
