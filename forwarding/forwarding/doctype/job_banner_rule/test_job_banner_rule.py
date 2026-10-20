# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestJobBannerRule(IntegrationTestCase):
	def test_unknown_condition_is_refused(self):
		rule = frappe.get_doc(
			{
				"doctype": "Job Banner Rule",
				"rule_code": "_T-BAD",
				"condition_key": "no_such_condition",
				"message_template": "x",
			}
		)
		self.assertRaises(frappe.ValidationError, rule.insert)

	def test_seeded_rules_exist(self):
		for code in ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"):
			self.assertTrue(frappe.db.exists("Job Banner Rule", code), code)
