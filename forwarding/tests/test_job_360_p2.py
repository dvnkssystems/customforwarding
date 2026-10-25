# Copyright (c) 2026, DVNKS Systems and contributors
"""Job 360 phase 2: Transportation / Custom Clearance, the shared child-table
rules, cut-off defaults, banner dates, the worklist and the setup checklist.

Uses the site's own masters, like test_job_360; everything is rolled back.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import banners
from forwarding.api import job_360, setup
from forwarding.forwarding.doctype.operations.operations import (
	make_custom_clearance,
	make_transportaion,
)
from forwarding.patches.v1_0.map_activity_statuses import map_status
from forwarding.patches.v1_0.set_service_statuses import clearance_status
from forwarding.tests.test_job_360 import add_estimate, make

TEST_USER = "worklist-p2@example.com"


def _documents(n=3):
	names = frappe.get_all("Document List", limit=n, pluck="name", order_by="name")
	if len(names) < n:
		raise frappe.DoesNotExistError(f"Test needs {n} Document List records")
	return names


def job_with_rows(**values):
	"""A job with one container and three documents: one per stage, the
	customs one not yet received."""
	docs = _documents()
	return make(
		mode_of_shipment=values.pop("mode_of_shipment", "Sea"),
		container_details=[{"container_no": "TCNU1234567", "size": "40", "container_type": "HC"}],
		document_table=[
			{"document": docs[0], "stage": "Documentation", "received": "Yes"},
			{"document": docs[1], "stage": "Customs Clearance", "received": "No"},
			{"document": docs[2], "stage": "Arrival", "received": "No"},
		],
		**values,
	)


def make_transportation(job, **values):
	return frappe.get_doc({"doctype": "Transportation", "operations": job.name, **values}).insert(
		ignore_permissions=True
	)


def make_clearance(job, **values):
	return frappe.get_doc(
		{
			"doctype": "Custom Clearance",
			"operations": job.name,
			"bayyan_number": "1001",
			"bayyan_date": nowdate(),
			**values,
		}
	).insert(ignore_permissions=True)


class P2TestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)


class TestServices(P2TestCase):
	def test_transportation_copies_job_rows_on_insert(self):
		job = job_with_rows()
		tt = make_transportation(job)
		tt.reload()
		self.assertEqual(tt.customer, job.customer)
		self.assertEqual(tt.transport_status, "Planned")
		self.assertEqual([r.container_no for r in tt.container_details], ["TCNU1234567"])
		self.assertEqual(len(tt.document_table), 3)

	def test_transportation_from_mapper_is_not_copied_twice(self):
		job = job_with_rows()
		tt = make_transportaion(job.name)
		self.assertEqual(len(tt.document_table), 3, "the mapper copies the rows")
		tt.insert(ignore_permissions=True)
		tt.reload()
		self.assertEqual(len(tt.document_table), 3)
		self.assertEqual(len(tt.container_details), 1)

	def test_transportation_keeps_its_own_rows(self):
		job = job_with_rows()
		tt = make_transportation(job, container_details=[{"container_no": "OWN0000001"}])
		tt.reload()
		self.assertEqual([r.container_no for r in tt.container_details], ["OWN0000001"])

	def test_clearance_copies_only_customs_documents(self):
		job = job_with_rows()
		cc = make_clearance(job)
		cc.reload()
		self.assertEqual(cc.customer, job.customer)
		self.assertEqual(cc.clearance_status, "Draft")
		self.assertEqual([r.stage for r in cc.document_table], ["Customs Clearance"])

	def test_clearance_from_mapper_is_not_copied_twice(self):
		job = job_with_rows()
		cc = make_custom_clearance(job.name)
		self.assertEqual([r.stage for r in cc.document_table], ["Customs Clearance"])
		cc.bayyan_number = "1002"
		cc.bayyan_date = nowdate()
		cc.insert(ignore_permissions=True)
		cc.reload()
		self.assertEqual(len(cc.document_table), 1)

	def test_expired_vehicle_and_driver_warn_without_blocking(self):
		job = make()
		tt = frappe.get_doc({"doctype": "Transportation", "operations": job.name})
		with patch("frappe.db.get_value", side_effect=lambda dt, *a, **k: add_days(nowdate(), -1)):
			tt.vehicle, tt.driver = "V-1", "D-1"
			lines = tt.warn_expired_papers()
		self.assertEqual(len(lines), 2)

	def test_clearance_status_mapping(self):
		self.assertEqual(clearance_status("Manifest Submission", None, None), "Submitted to Customs")
		self.assertEqual(clearance_status("Arrived to Port", "Working", None), "Submitted to Customs")
		self.assertEqual(clearance_status("Submitted Declaration", None, None), "Submitted to Customs")
		self.assertEqual(clearance_status("Inspection stage", None, None), "Under Review")
		self.assertEqual(clearance_status("Ready to Release", None, None), "Duty Assessed")
		self.assertEqual(clearance_status("Fully Release", "Working", None), "Released")
		self.assertEqual(clearance_status("", "Completed", None), "Released")
		self.assertEqual(clearance_status(None, None, "Released at port"), "Released")
		self.assertEqual(clearance_status("", "Working", None), "Draft")
		self.assertEqual(clearance_status(None, None, None), "Draft")


class TestChildTables(P2TestCase):
	def test_attached_document_is_received_today(self):
		docs = _documents(2)
		job = make(
			document_table=[
				{"document": docs[0], "received": "No", "attach": "/files/test.pdf"},
				{"document": docs[1], "received": "No"},
			]
		)
		attached, plain = job.document_table
		self.assertEqual((attached.received, str(attached.date)), ("Yes", nowdate()))
		self.assertEqual((plain.received, plain.date), ("No", None))

	def test_attach_keeps_an_entered_date(self):
		docs = _documents(1)
		job = make(document_table=[{"document": docs[0], "attach": "/files/a.pdf", "date": "2026-01-05"}])
		self.assertEqual(str(job.document_table[0].date), "2026-01-05")

	def test_activity_done_is_dated_today(self):
		job = make()
		tt = make_transportation(
			job,
			activity_template_table=[
				{"activity": "Pick up", "status": "Done"},
				{"activity": "Deliver", "status": "Pending"},
				{"activity": "Return", "status": "Done", "date": "2026-01-05"},
			],
		)
		done, pending, dated = tt.activity_template_table
		self.assertEqual(str(done.date), nowdate())
		self.assertIsNone(pending.date)
		self.assertEqual(str(dated.date), "2026-01-05")

	def test_cost_amount_is_cost(self):
		item = frappe.db.get_value("Item", {"disabled": 0}, "name")
		job = make(cost_table=[{"item": item, "cost": 250, "rate": 400}])
		self.assertEqual(job.cost_table[0].amount, 250)

	def test_activity_status_mapping(self):
		for text, expected in (
			("done", "Done"),
			("Completed", "Done"),
			(" in progress ", "In Progress"),
			("Working", "In Progress"),
			("Pending", "Pending"),
			("waiting on carrier", "Pending"),
			("", None),
			(None, None),
		):
			self.assertEqual(map_status(text), expected, text)


class TestCutoffs(P2TestCase):
	def test_default_cutoffs(self):
		sea = job_360.default_cutoffs("Sea", "Saudi Arabia")
		self.assertEqual(
			sea, ["Rail Cut-off", "Inland Cut-off", "Container Pickup", "SI Deadline", "Cargo Cut-off"]
		)
		self.assertIn("AES Deadline", job_360.default_cutoffs("Sea", "United States"))
		self.assertEqual(job_360.default_cutoffs("SEA-FCL", "France"), sea)
		self.assertEqual(job_360.default_cutoffs("Air", "United States"), ["SI Deadline", "Cargo Cut-off"])
		self.assertEqual(job_360.default_cutoffs("Land", "Saudi Arabia"), [])
		self.assertEqual(job_360.default_cutoffs(None, None), [])

	def test_aes_only_for_the_united_states(self):
		cutoff = {"milestone": "AES Deadline", "latest": add_days(nowdate(), 5)}
		with self.assertRaises(frappe.ValidationError):
			make(job_type="Export", mode_of_shipment="Sea", destination_country="Saudi Arabia", cutoffs=[cutoff])
		job = make(job_type="Export", mode_of_shipment="Sea", destination_country="United States", cutoffs=[cutoff])
		self.assertEqual(job.cutoffs[0].milestone, "AES Deadline")


class TestBannerDates(P2TestCase):
	def test_format_date(self):
		self.assertEqual(banners.format_date("2026-10-19"), "19 Oct 2026")
		self.assertEqual(banners.format_date("2026-10-05"), "5 Oct 2026")
		self.assertEqual(banners.format_date(None), "")

	def test_seeded_messages_use_it(self):
		job = make(etd_date=add_days(nowdate(), -2))
		b2 = [b for b in job_360.build(job.name)["banners"] if b["rule_code"] == "B2"]
		if not b2:
			self.skipTest("B2 is disabled on this site")
		self.assertIn(banners.format_date(job.etd_date), b2[0]["message"])


class TestWorklist(P2TestCase):
	def setUp(self):
		super().setUp()
		frappe.cache.delete_value("job_360_worklist_version")

	def test_shape_and_counters_match_job_banners(self):
		job = job_with_rows(etd_date=add_days(nowdate(), -1))
		# With an estimate, so its entries are not B9's: every draft on the site
		# without one fills the end of the list, where WORKLIST_LIMIT cuts it.
		add_estimate(job)
		result = job_360.worklist(scope="all")

		self.assertEqual(
			set(result), {"scope", "can_change_scope", "rules", "counters", "items"}
		)
		self.assertTrue(result["can_change_scope"])
		self.assertEqual(result["scope"], "all")
		codes = [r["rule_code"] for r in result["rules"]]
		self.assertEqual(set(result["counters"]), set(codes))
		for rule in result["rules"]:
			self.assertEqual(set(rule), {"rule_code", "label", "colour", "priority"})
		priorities = [i["priority"] for i in result["items"]]
		self.assertEqual(priorities, sorted(priorities))

		# Every job's worklist entries are the worklist rules among its banners.
		mine = {i["rule_code"] for i in result["items"] if i["job"] == job.name}
		expected = {b["rule_code"] for b in job_360.build(job.name)["banners"] if b["rule_code"] in codes}
		self.assertEqual(mine, expected)
		self.assertIn("B1", mine)
		item = next(i for i in result["items"] if i["job"] == job.name)
		self.assertEqual(
			set(item),
			{
				"job",
				"customer",
				"customer_name",
				"rule_code",
				"colour",
				"priority",
				"message",
				"action",
				"eta_date",
				"operations_status",
				"branch",
			},
		)

		# Counters count every matching job across the scope.
		totals = {}
		for name in frappe.get_all(
			"Operations",
			filters=[["docstatus", "<", 2], ["operations_status", "not in", ["Closed", "Cancelled"]]],
			pluck="name",
		):
			for b in job_360.build(name)["banners"]:
				if b["rule_code"] in codes:
					totals[b["rule_code"]] = totals.get(b["rule_code"], 0) + 1
		self.assertEqual({k: v for k, v in result["counters"].items() if v}, totals)

	def test_closed_jobs_are_left_out(self):
		job = job_with_rows()
		# Saving can't close a job with documents outstanding (R3-07); a job
		# closed before that rule still has to stay off the worklist.
		frappe.db.set_value("Operations", job.name, "operations_status", "Closed")
		result = job_360.build_worklist("Administrator", "all")
		self.assertNotIn(job.name, {i["job"] for i in result["items"]})

	def test_cache_is_dropped_when_a_job_changes(self):
		job = job_with_rows()
		before = job_360.worklist(scope="all")
		self.assertIn(job.name, {i["job"] for i in before["items"]})
		for row in job.document_table:
			row.received = "Yes"
		job.save()
		after = job_360.worklist(scope="all")
		self.assertNotIn("B1", {i["rule_code"] for i in after["items"] if i["job"] == job.name})

	def test_mine_scope_for_a_non_manager(self):
		user = _worklist_user()
		owned_by_admin = job_with_rows()
		assigned = job_with_rows()
		frappe.db.set_value("Operations", assigned.name, "_assign", json.dumps([user]))

		frappe.set_user(user)
		result = job_360.worklist(scope="all")
		self.assertFalse(result["can_change_scope"])
		self.assertEqual(result["scope"], "mine", "a non-manager cannot widen the scope")
		jobs = {i["job"] for i in result["items"]}
		self.assertIn(assigned.name, jobs)
		self.assertNotIn(owned_by_admin.name, jobs)

	def test_bad_scope(self):
		with self.assertRaises(frappe.ValidationError):
			job_360.worklist(scope="everyone")


def _worklist_user():
	if not frappe.db.exists("User", TEST_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": TEST_USER,
				"first_name": "Worklist",
				"send_welcome_email": 0,
				"roles": [{"role": "Sales Manager"}],
			}
		).insert(ignore_permissions=True)
	return TEST_USER


class TestSetupChecklist(P2TestCase):
	def setUp(self):
		super().setUp()
		frappe.defaults.clear_user_default(setup.DISMISSED_KEY)
		frappe.defaults.clear_user_default(setup.SKIPPED_KEY)

	def test_shape(self):
		result = setup.checklist()
		self.assertEqual(set(result), {"dismissed", "steps"})
		self.assertFalse(result["dismissed"])
		self.assertEqual(
			[s["key"] for s in result["steps"]],
			["customer", "supplier", "charge_items", "vehicles", "quote", "job", "team"],
		)
		for step in result["steps"]:
			self.assertEqual(set(step), {"key", "label", "done", "skippable", "skipped", "route"})
		steps = {s["key"]: s for s in result["steps"]}
		self.assertEqual(steps["customer"]["done"], frappe.db.count("Customer") >= 1)
		self.assertEqual(steps["job"]["route"], "/jobs/new")
		self.assertEqual([k for k, s in steps.items() if s["skippable"]], ["vehicles"])

	def test_dismiss(self):
		self.assertTrue(setup.dismiss()["dismissed"])
		self.assertTrue(setup.checklist()["dismissed"])

	def test_skip(self):
		with patch.object(setup, "STEPS", tuple(
			(k, label, (lambda: False) if k == "vehicles" else done, skippable, route)
			for k, label, done, skippable, route in setup.STEPS
		)):
			vehicles = next(s for s in setup.skip("vehicles")["steps"] if s["key"] == "vehicles")
		self.assertTrue(vehicles["skipped"])
		self.assertTrue(vehicles["done"], "a skipped step counts as done")
		with self.assertRaises(frappe.ValidationError):
			setup.skip("customer")
