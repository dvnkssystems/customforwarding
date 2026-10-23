# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 2, stream 3: the job's estimate and the Estimation vs Actual report.

M-01  the estimate lives on the cost sheet (Est. Cost / Est. Selling), typed
      in, and a job from a quote starts with the quote's charges as Est. Selling
M-02  a draft saves without an estimate; submit needs one; until then banner
      B9 "No estimate entered yet" and the worklist's "Estimate missing"
M-03  the job's figures on Job 360 are the report's row for the job
M-19  cancelled jobs are left out of the report by default
M-20  Var % only when the estimated profit is above zero

Runs against the site's demo masters; everything is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from forwarding import banners
from forwarding.api import job_360, job_lifecycle
from forwarding.estimation import job_figures
from forwarding.forwarding.report.estimation_vs_actual_summary_report__new import (
	estimation_vs_actual_summary_report__new as report,
)
from forwarding.tests.test_job_360 import ITEM, add_estimate, make, make_sales_invoice, submit_job


def report_rows(job, **filters):
	_columns, data, _message = report.execute(
		{"company": job.company, "job": job.name, "date_basis": "Job Date", "include_open": 1, **filters}
	)
	return data


class EstimateCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		frappe.cache.delete_keys("job_360")


class TestCostSheetIsTheEstimate(EstimateCase):
	# M-01 -------------------------------------------------------------------------

	def test_columns_read_est_cost_and_est_selling(self):
		meta = frappe.get_meta("Cost Table")
		self.assertEqual(meta.get_label("cost"), "Est. Cost")
		self.assertEqual(meta.get_label("rate"), "Est. Selling")

	def test_typed_estimate_survives_saving_with_an_item(self):
		"""The item's rates only fill an empty cell; a typed estimate stays."""
		job = make(cost_table=[{"item": ITEM, "cost": 123, "rate": 456}])
		job.reload()
		job.save()
		job.reload()
		self.assertEqual((job.cost_table[0].cost, job.cost_table[0].rate), (123, 456))

	def test_quote_charges_become_est_selling(self):
		from forwarding.quote_to_job import make_operations_from_quote

		customer = frappe.get_all("Customer", pluck="name", limit=1)[0]
		quote = frappe.get_doc(
			{
				"doctype": "Quote",
				"consignee": customer,
				"mode": "AIR",
				"date": nowdate(),
				"items": [
					{"description": "Air Freight", "rate": 100, "units": 3, "amount": 300},
					{"description": "Handling", "rate": 50, "units": 1, "amount": 50},
				],
			}
		).insert(ignore_permissions=True)
		quote.submit()

		job = make_operations_from_quote(quote.name)
		self.assertEqual([(r.item_name, r.rate) for r in job.cost_table], [("Air Freight", 300), ("Handling", 50)])
		self.assertTrue(banners.has_estimate(job))


class TestEstimateIsMandatory(EstimateCase):
	# M-02 -------------------------------------------------------------------------

	def test_draft_saves_without_an_estimate(self):
		job = make()
		self.assertEqual(job.docstatus, 0)
		self.assertFalse(job.cost_table)

	def test_submit_is_blocked_without_an_estimate(self):
		job = make()
		with self.assertRaisesRegex(frappe.ValidationError, "Add an estimate before submitting"):
			job.submit()
		self.assertEqual(frappe.db.get_value("Operations", job.name, "docstatus"), 0)

	def test_a_row_with_no_selling_is_not_an_estimate(self):
		job = make(cost_table=[{"item_name": "Trucking", "cost": 500, "rate": 0}])
		with self.assertRaisesRegex(frappe.ValidationError, "Add an estimate before submitting"):
			job.submit()

	def test_submit_goes_through_with_an_estimate(self):
		job = add_estimate(make(), selling=750)
		job.submit()
		self.assertEqual(frappe.db.get_value("Operations", job.name, "docstatus"), 1)

	def test_banner_until_an_estimate_is_entered(self):
		job = make()
		banner = next(b for b in job_360.build(job.name)["banners"] if b["rule_code"] == "B9")
		self.assertEqual(banner["message"], "No estimate entered yet")
		self.assertEqual(banner["action"], "add_estimate")

		add_estimate(job)
		self.assertNotIn("B9", {b["rule_code"] for b in job_360.build(job.name)["banners"]})

	def test_worklist_counts_estimate_missing(self):
		job = make()
		worklist = job_360.build_worklist("Administrator", "all")
		self.assertIn("B9", {r["rule_code"] for r in worklist["rules"]})
		label = next(r["label"] for r in worklist["rules"] if r["rule_code"] == "B9")
		self.assertEqual(label, "Estimate missing")
		before = worklist["counters"]["B9"]
		self.assertGreaterEqual(before, 1)

		add_estimate(job)
		after = job_360.build_worklist("Administrator", "all")["counters"]["B9"]
		self.assertEqual(after, before - 1)

	def test_cancelled_job_has_no_estimate_banner(self):
		job = submit_job(make())
		job_lifecycle.cancel_job(job.name)
		job = frappe.get_doc("Operations", job.name)
		job.cost_table = []
		self.assertFalse(banners.estimate_missing(job, {}))


class TestJobFiguresMatchTheReport(EstimateCase):
	# M-03 -------------------------------------------------------------------------

	def test_estimate_comes_from_the_cost_sheet(self):
		job = make(
			cost_table=[
				{"item_name": "Freight", "cost": 600, "rate": 1000},
				{"item_name": "Handling", "cost": 100, "rate": 300},
			]
		)
		row = report_rows(job)[0]
		self.assertEqual((row["estimated_income"], row["estimated_expense"]), (1300, 700))
		self.assertEqual(row["estimated_profit"], 600)

	def test_job_360_figures_equal_the_report_row(self):
		job = submit_job(make(cost_table=[{"item_name": "Freight", "cost": 600, "rate": 1000}]))
		# The invoice is tagged with the job's Project, as the invoice client
		# scripts do, so the ledger reaches the actuals.
		si = make_sales_invoice(job, amount=1500, submit=False)
		si.project = job.name
		for item in si.items:
			item.project = job.name
		si.save()
		si.submit()

		on_job = job_360.build(job.name)["estimate"]
		(in_report,) = report_rows(job)
		keys = (
			"estimated_income",
			"estimated_expense",
			"estimated_profit",
			"actual_income",
			"actual_expense",
			"actual_profit",
			"variance",
			"variance_pct",
		)
		self.assertEqual({k: on_job[k] for k in keys}, {k: in_report[k] for k in keys})
		self.assertEqual(on_job["estimated_income"], 1000)
		self.assertEqual(on_job["actual_income"], 1500)

	def test_job_figures_for_a_job_with_no_cost_rows(self):
		job = make()
		figures = job_figures(job.name)
		self.assertEqual((figures["estimated_income"], figures["variance_pct"]), (0, None))


class TestReportRules(EstimateCase):
	# M-19 / M-20 ------------------------------------------------------------------

	def test_cancelled_jobs_are_left_out_by_default(self):
		job = submit_job(make())
		job_lifecycle.cancel_job(job.name)

		self.assertEqual(report_rows(job), [])
		(row,) = report_rows(job, include_cancelled=1)
		self.assertEqual(row["status"], "Cancelled")
		# The job's own page still shows its figures.
		self.assertEqual(job_figures(job.name)["status"], "Cancelled")

	def test_cancelled_status_is_left_out_too(self):
		job = make(operations_status="Cancelled")
		self.assertEqual(report_rows(job), [])
		self.assertEqual(report_rows(job, include_cancelled=1)[0]["status"], "Cancelled")

	def test_var_pct_only_when_est_profit_is_positive(self):
		loss = make(cost_table=[{"item_name": "Freight", "cost": 2000, "rate": 1000}])
		level = make(cost_table=[{"item_name": "Freight", "cost": 1000, "rate": 1000}])
		gain = make(cost_table=[{"item_name": "Freight", "cost": 600, "rate": 1000}])

		self.assertIsNone(report_rows(loss)[0]["variance_pct"])
		self.assertIsNone(report_rows(level)[0]["variance_pct"])
		row = report_rows(gain)[0]
		# Nothing posted yet: actual profit 0 against an estimated 400.
		self.assertEqual(row["variance"], -400)
		self.assertEqual(row["variance_pct"], -100)
