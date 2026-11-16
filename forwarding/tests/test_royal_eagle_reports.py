# Copyright (c) 2026, DVNKS Systems and contributors
"""Royal Eagle reports and menu (T-26-11-00051): saved job lists run in the
app, the V3 and Estimated Job reports run, and the menu gets the entries."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import report_runner
from forwarding.patches.v1_0 import royal_eagle_reports_menu as patch
from forwarding.report_totals import sum_numeric

ITEM = "Custom UI Sidebar Item"


class TestRoyalEagleReports(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def saved_list(self, name="RE Test Saved List", filters=None):
		if frappe.db.exists("Report", name):
			frappe.delete_doc("Report", name, force=1)
		return frappe.get_doc(
			{
				"doctype": "Report",
				"report_name": name,
				"ref_doctype": "Operations",
				"report_type": "Report Builder",
				"is_standard": "No",
				"module": "Forwarding",
				"json": json.dumps(
					{
						"filters": filters or [],
						"fields": [["name", "Operations"], ["customer", "Operations"], ["no_such_field", "Operations"]],
						"order_by": "`tabOperations`.`modified` desc",
						"add_totals_row": True,
					}
				),
			}
		).insert(ignore_permissions=True)

	def test_sum_numeric_skips_text_and_blanks(self):
		rows = [{"cost": 10, "item": "A", "rate": None}, {"cost": 2.5, "rate": 4, "date": "2026-11-01"}]
		self.assertEqual(sum_numeric(rows), {"cost": 12.5, "rate": 4.0})
		self.assertEqual(sum_numeric([]), {})

	def test_saved_list_runs_with_its_columns_and_filters(self):
		report = self.saved_list(filters=[["Operations", "name", "=", "__no_such_job__"]])
		out = report_runner.run(report.name)
		# A field gone from the DocType is dropped, not an error.
		self.assertEqual([c["fieldname"] for c in out["columns"]], ["name", "customer"])
		self.assertEqual(out["result"], [])
		self.assertFalse(out["add_total_row"])

	def test_saved_list_rows_match_the_list(self):
		report = self.saved_list()
		out = report_runner.run(report.name)
		expected = frappe.get_list("Operations", limit=report_runner.MAX_ROWS, pluck="name")
		body = out["result"][:-1] if out["add_total_row"] else out["result"]
		self.assertEqual(sorted(r["name"] for r in body), sorted(expected))

	def test_other_report_types_go_to_query_report(self):
		out = report_runner.run("Estimation Vs Actual Summary V3", filters=json.dumps({}))
		self.assertEqual(out["columns"][0]["fieldname"], "operations")

	def test_v3_runs_with_blank_filters(self):
		from forwarding.forwarding.report.estimation_vs_actual_summary_v3 import (
			estimation_vs_actual_summary_v3 as v3,
		)

		columns, rows = v3.execute({})
		self.assertEqual(len(columns), 15)
		self.assertIsInstance(rows, list)
		with self.assertRaises(frappe.ValidationError):
			v3.execute({"from_date": "2026-12-31", "to_date": "2026-01-01"})

	def test_estimated_job_reports_run_without_pandas(self):
		from forwarding.forwarding.report.estimated_job_report_detailed import estimated_job_report_detailed as d
		from forwarding.forwarding.report.estimated_job_report_summary import estimated_job_report_summary as s

		company = frappe.db.get_value("Company", {}, "name")
		for module in (d, s):
			columns, _rows = module.execute(frappe._dict({"company": company}))
			self.assertTrue(columns)

	def test_placeholder_reports_are_not_runnable(self):
		self.assertFalse(patch.runnable("Detailed Job Report with Expense"))
		self.assertFalse(patch.runnable("No Such Report"))
		self.assertTrue(patch.runnable("Estimation Vs Actual Summary V3"))

	def test_patch_adds_menu_entries_once(self):
		if not frappe.db.exists("DocType", ITEM) or not patch.top_group("Reports"):
			self.skipTest("custom_ui menu is not set up on this site")
		self.saved_list("Dammam Jobs")
		patch.execute()
		self.assertTrue(frappe.db.exists(ITEM, {"target_report": "Dammam Jobs", "is_active": 1}))
		self.assertTrue(frappe.db.exists(ITEM, {"target_report": "Estimation Vs Actual Summary V3", "is_active": 1}))
		self.assertFalse(frappe.db.exists(ITEM, {"target_report": "Detailed Job Report with Expense"}))
		self.assertFalse(frappe.db.exists(ITEM, {"target_doctype": "Payment Items"}))
		count = frappe.db.count(ITEM)
		patch.execute()
		self.assertEqual(frappe.db.count(ITEM), count)
