# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 2, stream 1: cancel, delete and amend a job (R2-09, R2-11, R2-34),
a cancelled job's page and worklist (R2-10, R2-12), cut-offs listed once
(R2-27), the cost row's account (R2-28), commodity matching (R2-31) and the
More menu's new actions. Uses the site's own masters; everything is rolled
back."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import banners
from forwarding.api import job_360, job_lifecycle
from forwarding.forwarding.doctype.operations.operations import default_expense_account
from forwarding.patches.v1_0 import job_actions_amend_delete
from forwarding.quote_to_job import _match
from forwarding.tests.test_job_360 import ITEM, make, make_sales_invoice, submit_job
from forwarding.tests.test_job_360_p2 import make_transportation


def submitted(**values):
	job = make(**values)
	submit_job(job)
	return job


def make_purchase_invoice(job, amount=500, submit=True):
	pi = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": job.company,
			"supplier": frappe.db.get_value("Supplier", {"disabled": 0}, "name"),
			"operations": job.name,
			"bill_no": f"B-{frappe.generate_hash(length=6)}",
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"set_posting_time": 1,
			# Both mandatory on this site; the job's own Project.
			"cost_center": frappe.db.get_value("Cost Center", {"company": job.company, "is_group": 0}, "name"),
			"project": job.project or job.name,
			"items": [{"item_code": ITEM, "qty": 1, "rate": amount}],
		}
	)
	pi.insert(ignore_permissions=True)
	if submit:
		pi.submit()
	return pi


class LifecycleCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		frappe.cache.delete_keys("job_360")

	def assertThrowsNaming(self, fn, *names):
		with self.assertRaises(frappe.ValidationError) as caught:
			fn()
		for name in names:
			self.assertIn(name, str(caught.exception))


class TestCancel(LifecycleCase):
	def test_nothing_linked_cancels(self):
		job = submitted()
		job_lifecycle.cancel_job(job.name)
		self.assertEqual(frappe.db.get_value("Operations", job.name, "docstatus"), 2)

	def test_draft_job_cannot_be_cancelled(self):
		job = make()
		self.assertThrowsNaming(lambda: job_lifecycle.cancel_job(job.name), "Only a submitted job")

	def test_blocked_by_submitted_sales_invoice(self):
		job = submitted()
		si = make_sales_invoice(job)
		self.assertThrowsNaming(lambda: job_lifecycle.cancel_job(job.name), si.name, "Cancel")
		self.assertEqual(frappe.db.get_value("Operations", job.name, "docstatus"), 1)

	def test_blocked_by_submitted_purchase_invoice(self):
		job = submitted()
		pi = make_purchase_invoice(job)
		self.assertThrowsNaming(lambda: job_lifecycle.cancel_job(job.name), pi.name)

	def test_blocked_by_transportation(self):
		job = submitted()
		tt = make_transportation(job)
		self.assertThrowsNaming(lambda: job_lifecycle.cancel_job(job.name), tt.name)
		check = job_lifecycle.check(job.name)
		self.assertEqual([r["name"] for r in check["cancel"]["blockers"]], [tt.name])

	def test_cancelled_invoice_does_not_block(self):
		job = submitted()
		si = make_sales_invoice(job)
		si.cancel()
		job_lifecycle.cancel_job(job.name)
		self.assertEqual(frappe.db.get_value("Operations", job.name, "docstatus"), 2)

	def test_drafts_need_confirmation_then_go_with_the_cancel(self):
		job = submitted()
		si = make_sales_invoice(job, submit=False)
		pi = make_purchase_invoice(job, submit=False)

		check = job_lifecycle.check(job.name)
		self.assertFalse(check["cancel"]["blockers"])
		self.assertEqual({r["name"] for r in check["cancel"]["drafts"]}, {si.name, pi.name})

		self.assertThrowsNaming(lambda: job_lifecycle.cancel_job(job.name), si.name, pi.name)
		self.assertEqual(frappe.db.get_value("Operations", job.name, "docstatus"), 1)

		result = job_lifecycle.cancel_job(job.name, delete_drafts=1)
		self.assertEqual(result["docstatus"], 2)
		self.assertFalse(frappe.db.exists("Sales Invoice", si.name))
		self.assertFalse(frappe.db.exists("Purchase Invoice", pi.name))


class TestDelete(LifecycleCase):
	def test_draft_job_is_deleted(self):
		job = make()
		job_lifecycle.delete_job(job.name)
		self.assertFalse(frappe.db.exists("Operations", job.name))

	def test_cancelled_job_is_deleted(self):
		job = submitted()
		job_lifecycle.cancel_job(job.name)
		job_lifecycle.delete_job(job.name)
		self.assertFalse(frappe.db.exists("Operations", job.name))

	def test_submitted_job_is_refused(self):
		job = submitted()
		self.assertThrowsNaming(lambda: job_lifecycle.delete_job(job.name), "Cancel it first")
		self.assertTrue(frappe.db.exists("Operations", job.name))

	def test_linked_invoice_blocks_and_is_named(self):
		job = make()
		si = make_sales_invoice(job, submit=False)
		self.assertThrowsNaming(lambda: job_lifecycle.delete_job(job.name), si.name, "Sales Invoice")
		self.assertTrue(frappe.db.exists("Operations", job.name))

	def test_payment_blocks_and_is_named(self):
		from forwarding.tests.test_job_360 import make_payment

		job = make()
		si = make_sales_invoice(job)
		pe = make_payment(si, 100)
		links = {r["name"] for r in job_lifecycle.linked_records(job.name)}
		self.assertTrue({si.name, pe.name} <= links)
		self.assertThrowsNaming(lambda: job_lifecycle.delete_job(job.name), pe.name, si.name)


class TestAmend(LifecycleCase):
	def test_only_a_cancelled_job(self):
		job = submitted()
		self.assertThrowsNaming(lambda: job_lifecycle.amend_job(job.name), "Only a cancelled job")

	def test_copy_is_a_draft_linked_to_the_cancelled_job(self):
		job = submitted(remarks="Amend me")
		job_lifecycle.cancel_job(job.name)
		copy = job_lifecycle.amend_job(job.name)
		self.assertEqual(copy["amended_from"], job.name)
		self.assertEqual(copy["docstatus"], 0)
		self.assertFalse(copy.get("name"))

		amended = frappe.get_doc(copy)
		amended.insert(ignore_permissions=True)
		self.assertEqual(amended.name, f"{job.name}-1")
		self.assertEqual(amended.customer, job.customer)

		# One live amendment per cancelled job; deleting the original waits for it.
		self.assertThrowsNaming(lambda: job_lifecycle.amend_job(job.name), amended.name)
		self.assertThrowsNaming(lambda: job_lifecycle.delete_job(job.name), amended.name)


class TestCancelledJobPage(LifecycleCase):
	def test_no_banners_no_free_time_no_worklist(self):
		job = submitted(eta_date=add_days(nowdate(), -20), free_time_days=3, operations_status="Ops Completed")
		self.assertTrue(job_360.build(job.name)["banners"])
		job_lifecycle.cancel_job(job.name)

		payload = job_360.build(job.name)
		self.assertEqual(payload["banners"], [])
		self.assertIsNone(payload["kpis"]["free_days_left"])
		self.assertNotIn("free_time", {m["key"] for m in payload["milestones"]})

		job.reload()
		self.assertEqual(banners.evaluate(job, {}), [])
		worklist = job_360.build_worklist("Administrator", "all")
		self.assertNotIn(job.name, {i["job"] for i in worklist["items"]})


class TestCutoffsOnce(LifecycleCase):
	def test_cutoffs_are_not_milestones(self):
		job = make(job_type="Export", mode_of_shipment="Air")
		payload = job_360.build(job.name)
		self.assertEqual([c["milestone"] for c in payload["cutoffs"]], ["SI Deadline", "Cargo Cut-off"])
		self.assertFalse([m for m in payload["milestones"] if m["key"].startswith("cutoff_")])


class TestCostAccount(LifecycleCase):
	def test_item_without_defaults_takes_the_company_expense_account(self):
		job = make(cost_table=[{"item": ITEM, "cost": 100, "rate": 150}])
		expected = default_expense_account(ITEM, job.company)
		self.assertTrue(expected)
		self.assertEqual(job.cost_table[0].account, expected)
		# Selling Amount (rate) is kept as typed (R2-29).
		self.assertEqual(job.cost_table[0].rate, 150)

	def test_a_chosen_account_is_kept(self):
		other = frappe.db.get_value(
			"Account", {"company": frappe.db.get_value("Company", {}, "name"), "is_group": 0, "root_type": "Expense"}, "name"
		)
		job = make(cost_table=[{"item": ITEM, "account": other, "cost": 100}])
		self.assertEqual(job.cost_table[0].account, other)


class TestCommodityMatch(LifecycleCase):
	def test_case_and_spacing_ignored_wildcards_not(self):
		name = frappe.get_doc({"doctype": "Commodity", "commodity": "R2 TEST SOCKS"}).insert().name
		self.assertEqual(_match("Commodity", "r2 test socks"), name)
		self.assertEqual(_match("Commodity", "  R2   Test Socks "), name)
		self.assertIsNone(_match("Commodity", "R2 TEST SOCK_"))
		self.assertIsNone(_match("Commodity", "R2 TEST%"))


class TestMoreMenu(LifecycleCase):
	def test_patch_adds_amend_and_delete_once(self):
		props = {
			"actions": [
				{"key": "cancel", "label": "Cancel job", "group": "more", "icon": "ban"},
				{"key": "duplicate", "label": "Duplicate", "group": "more", "icon": "copy"},
				{"key": "audit_log", "label": "History", "group": "extra", "icon": "history"},
				{"key": "edit", "label": "Edit", "group": None, "icon": "pencil"},
			]
		}
		new = job_actions_amend_delete.add_actions(props)
		self.assertEqual([a["key"] for a in new["actions"]], ["cancel", "amend", "duplicate", "audit_log", "delete", "edit"])
		self.assertEqual(new["actions"][4]["group"], "extra")
		self.assertIsNone(job_actions_amend_delete.add_actions(new))

	def test_hidden_entry_is_left_alone(self):
		props = {"actions": [{"key": "delete", "hidden": 1}, {"key": "amend", "hidden": 1}]}
		self.assertIsNone(job_actions_amend_delete.add_actions(props))
		self.assertEqual(json.loads(json.dumps(props)), props)
