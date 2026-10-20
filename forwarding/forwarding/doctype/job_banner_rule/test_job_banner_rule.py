# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from forwarding import customer_banners, supplier_banners
from forwarding.job_events import customer_cache_key, supplier_cache_key


def customer_ctx(**overrides):
	ctx = {
		"kpis": {"credit_used": 1500, "credit_limit": 1000, "credit_pct": 150},
		"currency": "SAR",
		"overdue": [
			{"name": "SINV-T1", "due_date": getdate("2026-09-01"), "outstanding": 100},
			{"name": "SINV-T2", "due_date": getdate("2026-08-15"), "outstanding": 50},
		],
		"expiring_quotes": [{"name": "QT-T1", "validity": getdate("2026-10-21")}],
		"today": getdate("2026-10-20"),
	}
	ctx.update(overrides)
	return ctx


def supplier_ctx(**overrides):
	ctx = {
		"kpis": {},
		"currency": "SAR",
		"overdue": [{"name": "PINV-T1", "due_date": getdate("2026-09-01"), "outstanding": 70}],
		"unbilled_done": [{"doctype": "Transportation", "name": "TR-T1"}],
		"supplier": {"status": "Blocked"},
		"hold_type": None,
		"release_date": None,
		"today": getdate("2026-10-20"),
	}
	ctx.update(overrides)
	return ctx


def codes(banners):
	return [b["code"] for b in banners]


class TestJobBannerRule(IntegrationTestCase):
	def setUp(self):
		# Rules are shared rows; undo each test's edits before the next one.
		frappe.db.savepoint("banner_rule_test")

	def tearDown(self):
		frappe.db.rollback(save_point="banner_rule_test")
		frappe.cache.delete_keys("customer_360:")
		frappe.cache.delete_keys("supplier_360:")

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

	def test_condition_must_belong_to_applies_to(self):
		# over_credit_limit is a Customer condition, not a job one.
		rule = frappe.get_doc(
			{
				"doctype": "Job Banner Rule",
				"rule_code": "_T-WRONG-PAGE",
				"applies_to": "Operations",
				"condition_key": "over_credit_limit",
				"message_template": "x",
			}
		)
		self.assertRaises(frappe.ValidationError, rule.insert)

	def test_seeded_rules_exist(self):
		expected = {
			"Operations": ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"),
			"Customer": ("C1", "C2", "C3"),
			"Supplier": ("S1", "S2", "S3"),
		}
		for applies_to, rule_codes in expected.items():
			for code in rule_codes:
				self.assertEqual(frappe.db.get_value("Job Banner Rule", code, "applies_to"), applies_to, code)

	def test_customer_banners_come_from_rules(self):
		banners = customer_banners.evaluate(customer_ctx())
		self.assertEqual(codes(banners), ["C1", "C2", "C3"])
		by_code = {b["code"]: b for b in banners}
		self.assertTrue(by_code["C1"]["message"].startswith("Over credit limit: "), by_code["C1"]["message"])
		self.assertTrue(by_code["C2"]["message"].startswith("2 invoices overdue: "), by_code["C2"]["message"])
		self.assertIn("oldest due 15 Aug 2026", by_code["C2"]["message"])
		self.assertEqual(by_code["C3"]["message"], "Quote QT-T1 expires 21 Oct 2026")
		self.assertEqual(by_code["C3"]["action"], "view_quotes")

	def test_disabled_customer_rule_is_gone(self):
		frappe.db.set_value("Job Banner Rule", "C2", "enabled", 0)
		self.assertEqual(codes(customer_banners.evaluate(customer_ctx())), ["C1", "C3"])

	def test_edited_customer_message_is_used(self):
		rule = frappe.get_doc("Job Banner Rule", "C3")
		rule.message_template = "{{ ctx.expiring_quotes|length }} quote(s) about to lapse"
		rule.save()
		c3 = next(b for b in customer_banners.evaluate(customer_ctx()) if b["code"] == "C3")
		self.assertEqual(c3["message"], "1 quote(s) about to lapse")

	def test_supplier_banners_come_from_rules(self):
		banners = supplier_banners.evaluate(supplier_ctx())
		self.assertEqual(codes(banners), ["S1", "S2", "S3"])
		messages = {b["code"]: b["message"] for b in banners}
		self.assertTrue(messages["S1"].startswith("1 bill overdue: "), messages["S1"])
		self.assertEqual(messages["S2"], "1 service delivered with no supplier invoice")
		self.assertEqual(messages["S3"], "Supplier is blocked")

		on_hold = supplier_banners.evaluate(
			supplier_ctx(supplier={"status": "On Hold"}, hold_type="Payments", release_date=getdate("2026-11-01"))
		)
		s3 = next(b for b in on_hold if b["code"] == "S3")
		self.assertEqual(s3["message"], "Supplier is on hold for payments until 1 Nov 2026")

	def test_priority_orders_party_banners(self):
		frappe.db.set_value("Job Banner Rule", "S3", "priority", 1)
		self.assertEqual(codes(supplier_banners.evaluate(supplier_ctx())), ["S3", "S1", "S2"])

	def test_rule_save_clears_party_caches(self):
		frappe.cache.set_value(customer_cache_key("_T-CUST"), {"x": 1})
		frappe.cache.set_value(supplier_cache_key("_T-SUPP"), {"x": 1})
		frappe.get_doc("Job Banner Rule", "S2").save()
		self.assertIsNone(frappe.cache.get_value(customer_cache_key("_T-CUST")))
		self.assertIsNone(frappe.cache.get_value(supplier_cache_key("_T-SUPP")))

	def test_party_rules_never_count_on_the_worklist(self):
		rule = frappe.get_doc("Job Banner Rule", "C1")
		rule.show_on_worklist = 1
		rule.save()
		self.assertEqual(rule.show_on_worklist, 0)
