# Copyright (c) 2026, DVNKS Systems and contributors
"""Supplier 360: payload shape, roles, KPIs, banners S1-S3, the permission
gate and cache invalidation.

Each test makes its own supplier so the numbers are its own; it uses the
site's company, item, project, cost centre and accounts (like
test_customer_360) and everything is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import supplier_banners
from forwarding.api import supplier_360
from forwarding.job_events import supplier_cache_key
from forwarding.party_360 import default_company
from forwarding.tests.test_job_360 import ITEM, _first, make

NO_ROLE_USER = "supplier360-norole@example.com"


def make_supplier(**values):
	company = default_company()
	# The company has no default payable account; the demo suppliers each
	# carry one, so borrow theirs.
	payable = _first("Party Account", {"parenttype": "Supplier", "company": company})
	payable = frappe.db.get_value("Party Account", payable, "account")
	return frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": f"S360 Test {frappe.generate_hash(length=6)}",
			"supplier_type": "Company",
			"supplier_group": _first("Supplier Group", {"is_group": 0}),
			# Mandatory on this site (Property Setter / Custom Field).
			"branch": _first("Branch", {"abbreviation": ["is", "set"]}),
			"tax_id": "300000000000003",
			"default_currency": frappe.get_cached_value("Company", company, "default_currency"),
			"accounts": [{"company": company, "account": payable}],
			**values,
		}
	).insert(ignore_permissions=True)


def make_bill(supplier, amount, due_in_days=0, job=None, submit=True):
	"""A Purchase Invoice due due_in_days from today (negative: already overdue)."""
	company = default_company()
	due = add_days(nowdate(), due_in_days)
	posting = min(nowdate(), due)
	pi = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"operations": job,
			"bill_no": f"B-{frappe.generate_hash(length=6)}",
			"posting_date": posting,
			"due_date": due,
			"set_posting_time": 1,
			# Both mandatory on this site.
			"cost_center": _first("Cost Center", {"company": company, "is_group": 0}),
			"project": _first("Project"),
			"items": [{"item_code": ITEM, "qty": 1, "rate": amount}],
		}
	)
	pi.insert(ignore_permissions=True)
	if submit:
		pi.submit()
	return pi


def make_bill_payment(pi, amount):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry("Purchase Invoice", pi.name, party_amount=amount)
	pe.reference_no = "TEST"
	pe.reference_date = nowdate()
	pe.mode_of_payment = frappe.db.get_value("Mode of Payment Account", {"company": pi.company}, "parent")
	pe.type = "Test"
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def make_transport(job, transporter, status="Planned"):
	return frappe.get_doc(
		{
			"doctype": "Transportation",
			"operations": job.name,
			"transporter": transporter,
			"transport_status": status,
		}
	).insert(ignore_permissions=True)


def make_clearance(job, broker=None, transporter=None, status="Draft"):
	return frappe.get_doc(
		{
			"doctype": "Custom Clearance",
			"operations": job.name,
			"broker_name": broker,
			"transporter_name": transporter,
			"clearance_status": status,
			"bayyan_number": frappe.generate_hash(length=8),
			"bayyan_date": nowdate(),
		}
	).insert(ignore_permissions=True)


def fresh(supplier):
	frappe.cache.delete_value(supplier_cache_key(supplier))
	return supplier_360.get(supplier)


def is_cached(supplier):
	return frappe.cache.get_value(supplier_cache_key(supplier)) is not None


def codes(payload):
	return [b["code"] for b in payload["banners"]]


class TestSupplier360(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Production-copied sites carry Server Scripts that raise when server
		# scripts are disabled; not what is under test.
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.supplier = make_supplier()

	def test_shape(self):
		job = make(handling_agent=self.supplier.name)
		make_bill(self.supplier.name, 500, due_in_days=10, job=job.name)
		make_transport(job, self.supplier.name)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Saad",
				"email_ids": [{"email_id": "saad.s360@example.com", "is_primary": 1}],
				"links": [{"link_doctype": "Supplier", "link_name": self.supplier.name}],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Depot",
				"address_type": "Billing",
				"address_line1": "Port Road",
				"city": "Dammam",
				"country": "Saudi Arabia",
				"links": [{"link_doctype": "Supplier", "link_name": self.supplier.name}],
			}
		).insert(ignore_permissions=True)

		data = fresh(self.supplier.name)
		self.assertEqual(
			set(data),
			{
				"currency", "supplier", "kpis", "banners", "jobs", "services", "invoices", "payments", "documents",
				"party_documents", "contacts", "addresses",
			},
		)
		self.assertEqual(
			set(data["supplier"]),
			{
				"name", "supplier_name", "supplier_group", "country", "tax_id", "supplier_code", "cr_no", "roles",
				"disabled", "status", "default_currency", "payment_terms", "primary_contact", "primary_address",
			},
		)
		self.assertEqual(
			set(data["kpis"]),
			{
				"active_jobs", "open_services", "payable_outstanding", "overdue", "unbilled_services",
				"billed_this_year", "cost_variance", "documents_on_file", "documents_total",
				"party_documents_count", "party_documents_expiring", "party_documents_expired",
			},
		)
		s = data["supplier"]
		self.assertEqual(s["status"], "Active")
		self.assertEqual(s["tax_id"], "300000000000003")
		self.assertTrue(s["supplier_code"], "set on insert by forwarding.naming")
		self.assertEqual(s["primary_contact"]["name"], contact.name)
		self.assertEqual(s["primary_contact"]["email_id"], "saad.s360@example.com")
		self.assertIn("Port Road", s["primary_address"]["address_display"])

		self.assertEqual([j["name"] for j in data["jobs"]], [job.name])
		self.assertEqual(
			set(data["jobs"][0]),
			{
				"name", "roles", "operations_status", "mode_of_shipment", "job_type", "customer",
				"customer_name", "port_of_loading", "port_of_destination", "eta_date", "date", "docstatus",
			},
		)
		self.assertTrue(data["jobs"][0]["customer_name"])
		self.assertEqual(
			set(data["services"][0]),
			{"doctype", "name", "operations", "role", "status", "date", "docstatus", "billed"},
		)
		self.assertIs(data["services"][0]["billed"], True, "the job has a submitted bill from the supplier")
		inv = data["invoices"][0]
		self.assertEqual(
			set(inv),
			{
				"name", "bill_no", "posting_date", "due_date", "grand_total", "outstanding_amount", "status",
				"docstatus", "operations", "overdue",
			},
		)
		self.assertEqual(inv["operations"], job.name)
		self.assertIs(inv["overdue"], False)
		self.assertIsInstance(inv["posting_date"], str)
		self.assertEqual(len(data["contacts"]), 1)
		self.assertEqual(data["addresses"][0]["city"], "Dammam")

	def test_roles(self):
		name = self.supplier.name
		agent = make(handling_agent=name)
		listed = make(suppliers=[{"supplier": name}])
		legs = make(transport_container_legs=[{"transporter": name}])
		trucked = make()
		make_transport(trucked, name)
		cleared = make()
		make_clearance(cleared, broker=name, transporter=name)
		make(handling_agent=make_supplier().name)  # someone else's job

		data = fresh(name)
		roles = {j["name"]: j["roles"] for j in data["jobs"]}
		self.assertEqual(
			roles,
			{
				agent.name: ["Handling agent"],
				listed.name: ["Supplier"],
				legs.name: ["Transporter"],
				trucked.name: ["Transporter"],
				cleared.name: ["Transporter", "Broker"],
			},
		)
		self.assertEqual(
			{(s["doctype"], s["role"]) for s in data["services"]},
			{("Transportation", "Transporter"), ("Custom Clearance", "Broker, Transporter")},
		)
		self.assertEqual(data["kpis"]["active_jobs"], 5)

	def test_kpis_active_and_open_services(self):
		name = self.supplier.name
		make(handling_agent=name, operations_status="Closed")
		open_job = make(handling_agent=name)
		make_transport(open_job, name, "Dispatched")
		make_transport(make(), name, "Delivered")
		make_clearance(make(), broker=name, status="Under Review")
		make_clearance(make(), broker=name, status="Released")

		k = fresh(name)["kpis"]
		self.assertEqual(k["active_jobs"], 4, "the closed job is not active")
		self.assertEqual(k["open_services"], 2, "dispatched + under review")
		self.assertEqual(k["unbilled_services"], 4, "no bills at all")

	def test_kpis_payables_overdue_billed(self):
		name = self.supplier.name
		job = make(handling_agent=name)
		current = make_bill(name, 1000, due_in_days=15, job=job.name)
		late = make_bill(name, 400, due_in_days=-10)
		make_bill(name, 9999, submit=False)  # drafts do not count

		k = fresh(name)["kpis"]
		self.assertEqual(k["payable_outstanding"], current.outstanding_amount + late.outstanding_amount)
		self.assertEqual(k["overdue"], late.outstanding_amount)
		self.assertEqual(k["billed_this_year"], current.base_grand_total + late.base_grand_total)

		make_bill_payment(late, late.outstanding_amount)
		k = fresh(name)["kpis"]
		self.assertEqual(k["payable_outstanding"], current.outstanding_amount)
		self.assertEqual(k["overdue"], 0)

	def test_unbilled_services(self):
		name = self.supplier.name
		billed_job = make()
		unbilled_job = make()
		make_transport(billed_job, name, "Delivered")
		make_transport(unbilled_job, name, "Delivered")
		make_clearance(unbilled_job, broker=name, status="Draft")
		make_bill(name, 100, due_in_days=30, job=billed_job.name)
		# A draft bill, or another supplier's bill, does not bill the service.
		make_bill(name, 100, job=unbilled_job.name, submit=False)
		make_bill(make_supplier().name, 100, due_in_days=30, job=unbilled_job.name)

		data = fresh(name)
		billed = {s["operations"]: s["billed"] for s in data["services"] if s["doctype"] == "Transportation"}
		self.assertEqual(billed, {billed_job.name: True, unbilled_job.name: False})
		self.assertEqual(data["kpis"]["unbilled_services"], 2, "the delivered truck + the draft clearance")

	def test_documents_on_file(self):
		docs = frappe.get_all("Document List", limit=2, pluck="name", order_by="name")
		if len(docs) < 2:
			self.skipTest("needs two Document List records")
		transport = frappe.get_doc(
			{
				"doctype": "Transportation",
				"operations": make().name,
				"transporter": self.supplier.name,
				"document_table": [
					{"document": docs[0], "stage": "Documentation", "received": "Yes"},
					{"document": docs[1], "stage": "Arrival", "received": "No"},
				],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "s360-licence.txt",
				"content": b"licence",
				"attached_to_doctype": "Supplier",
				"attached_to_name": self.supplier.name,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)

		data = fresh(self.supplier.name)
		self.assertEqual(data["kpis"]["documents_on_file"], 2, "one received row + one file")
		sources = {(d["source_doctype"], d["source_name"]) for d in data["documents"]}
		self.assertEqual(sources, {("Transportation", transport.name), ("Supplier", self.supplier.name)})

	def test_banner_s1_overdue_payables(self):
		make_bill(self.supplier.name, 300, due_in_days=5)
		self.assertNotIn("S1", codes(fresh(self.supplier.name)))

		first = make_bill(self.supplier.name, 200, due_in_days=-3)
		make_bill(self.supplier.name, 100, due_in_days=-1)
		data = fresh(self.supplier.name)
		s1 = next(b for b in data["banners"] if b["code"] == "S1")
		self.assertEqual((s1["colour"], s1["action"]), ("critical", "view_invoices"))
		self.assertTrue(s1["message"].startswith("2 bills overdue"), s1["message"])
		self.assertIn(supplier_banners.format_date(first.due_date), s1["message"])
		self.assertEqual(sum(1 for i in data["invoices"] if i["overdue"]), 2)

	def test_banner_s2_unbilled_services(self):
		name = self.supplier.name
		make_transport(make(), name, "Dispatched")  # not finished: no nudge yet
		make_clearance(make(), broker=name, status="Rejected")  # nothing to bill
		self.assertNotIn("S2", codes(fresh(name)))

		make_transport(make(), name, "Container Returned")
		make_clearance(make(), broker=name, status="Released")
		data = fresh(name)
		s2 = next(b for b in data["banners"] if b["code"] == "S2")
		self.assertEqual((s2["colour"], s2["action"]), ("warning", "view_services"))
		self.assertEqual(s2["message"], "2 services delivered with no supplier invoice")

	def test_banner_s3_on_hold_or_blocked(self):
		self.assertNotIn("S3", codes(fresh(self.supplier.name)))

		self.supplier.db_set({"on_hold": 1, "hold_type": "Payments", "release_date": add_days(nowdate(), 5)})
		data = fresh(self.supplier.name)
		self.assertEqual(data["supplier"]["status"], "On Hold")
		s3 = next(b for b in data["banners"] if b["code"] == "S3")
		self.assertEqual((s3["colour"], s3["action"]), ("critical", "edit"))
		self.assertIn("payments", s3["message"])

		# Past its release date the hold is over.
		self.supplier.db_set("release_date", add_days(nowdate(), -1))
		self.assertEqual(fresh(self.supplier.name)["supplier"]["status"], "Active")

		self.supplier.db_set("is_blocked", 1)
		data = fresh(self.supplier.name)
		self.assertEqual(data["supplier"]["status"], "Blocked")
		self.assertIn("S3", codes(data))

		self.supplier.db_set("disabled", 1)
		data = fresh(self.supplier.name)
		self.assertEqual(data["supplier"]["status"], "Disabled")
		self.assertNotIn("S3", codes(data))

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
		self.assertRaises(frappe.PermissionError, supplier_360.get, self.supplier.name)

	def test_lists_hidden_without_doctype_read(self):
		make_bill(self.supplier.name, 100, due_in_days=5)
		fresh(self.supplier.name)
		with patch.object(
			frappe, "has_permission", side_effect=lambda doctype, *a, **kw: doctype != "Purchase Invoice"
		):
			data = supplier_360.get(self.supplier.name)
		self.assertEqual(data["invoices"], [])
		self.assertEqual(data["kpis"]["payable_outstanding"], 100)

	def test_cache_invalidation(self):
		name = self.supplier.name

		def assert_cleared(action, label):
			supplier_360.get(name)
			self.assertTrue(is_cached(name))
			action()
			self.assertFalse(is_cached(name), f"{label} should drop the cache")

		job = make(handling_agent=name)
		assert_cleared(lambda: job.save(ignore_permissions=True), "job save")

		def drop_agent():
			job.handling_agent = None
			job.save(ignore_permissions=True)

		assert_cleared(drop_agent, "job losing its handling agent")

		def add_leg():
			job.append("transport_package_legs", {"transporter": name})
			job.save(ignore_permissions=True)

		assert_cleared(add_leg, "transport leg added")

		other = make()
		transport = make_transport(other, None)

		def assign_transport():
			transport.transporter = name
			transport.save(ignore_permissions=True)

		assert_cleared(assign_transport, "transport assigned")

		def unassign_transport():
			transport.transporter = None
			transport.save(ignore_permissions=True)

		assert_cleared(unassign_transport, "transport unassigned (old value)")
		clearance = make_clearance(other, broker=name)
		assert_cleared(lambda: other.save(ignore_permissions=True), "job of a service saved")
		assert_cleared(
			lambda: frappe.delete_doc("Custom Clearance", clearance.name, ignore_permissions=True),
			"clearance delete",
		)

		pi = make_bill(name, 100, submit=False)
		assert_cleared(pi.submit, "bill submit")
		pi.reload()
		assert_cleared(lambda: make_bill_payment(pi, 50), "payment submit")
		assert_cleared(lambda: self.supplier.save(ignore_permissions=True), "supplier save")
		assert_cleared(
			lambda: frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Cache",
					"links": [{"link_doctype": "Supplier", "link_name": name}],
				}
			).insert(ignore_permissions=True),
			"contact insert",
		)
		assert_cleared(
			lambda: frappe.get_doc(
				{
					"doctype": "File",
					"file_name": "s360-cache.txt",
					"content": b"x",
					"attached_to_doctype": "Supplier",
					"attached_to_name": name,
					"is_private": 1,
				}
			).insert(ignore_permissions=True),
			"file attach",
		)

	def test_cached_for_a_minute(self):
		fresh(self.supplier.name)
		self.assertTrue(is_cached(self.supplier.name))
		with patch.object(supplier_360, "build", side_effect=AssertionError("should be cached")):
			supplier_360.get(self.supplier.name)
