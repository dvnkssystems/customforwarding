# Copyright (c) 2026, DVNKS Systems and contributors
"""Banners that act in place and can be dismissed (A-22)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from forwarding import banner_dismissal, banners
from forwarding.api import job_360
from forwarding.tests.test_job_360 import make


def rule(condition_key, code="T1", action=None):
	return frappe._dict(
		rule_code=code, label=code, priority=1, condition_key=condition_key, message_template="{{ ctx.msg }}", action=action, colour="warning"
	)


class TestBanners(IntegrationTestCase):
	def test_overdue_banner_acts_on_its_invoice(self):
		job = make()
		ctx = {"overdue_invoices": ["SI-2", "SI-1"], "msg": "2 overdue"}
		(b,) = banners.evaluate(job, ctx, rules=[rule("invoice_overdue", action="view_invoice")])
		self.assertEqual(b["actions"], ["record_payment", "send_reminder"])
		self.assertEqual(b["invoice"], "SI-2")
		more = banners.evaluate(job, {**ctx, "overdue_invoices": ["SI-1", "SI-2", "SI-3"]}, rules=[rule("invoice_overdue")])[0]
		self.assertNotEqual(b["fingerprint"], more["fingerprint"])

	def test_free_time_comes_back_on_its_last_day(self):
		job = make()
		r = [rule("free_time_expiring")]
		three = banners.evaluate(job, {"free_days_left": 3, "msg": "3 days"}, rules=r)[0]["fingerprint"]
		two = banners.evaluate(job, {"free_days_left": 2, "msg": "2 days"}, rules=r)[0]["fingerprint"]
		last = banners.evaluate(job, {"free_days_left": 1, "msg": "1 day"}, rules=r)[0]["fingerprint"]
		self.assertEqual(three, two)
		self.assertNotEqual(two, last)

	def test_delivery_clears_free_time(self):
		job = make()
		job.delivery_date = nowdate()
		self.assertFalse(banners.free_time_expiring(job, {"free_days_left": 1}))

	def test_dismissed_until_it_changes(self):
		job = make()
		shown = [{"rule_code": "T1", "fingerprint": "a"}, {"rule_code": "T2", "fingerprint": "b"}]
		banner_dismissal.dismiss("Operations", job.name, "T1", "a")
		self.assertEqual([b["rule_code"] for b in banner_dismissal.hide_dismissed("Operations", job.name, shown)], ["T2"])
		changed = [{"rule_code": "T1", "fingerprint": "c"}]
		self.assertEqual(banner_dismissal.hide_dismissed("Operations", job.name, changed), changed)

	def test_record_delivery(self):
		job = make()
		job_360.record_delivery(job.name, nowdate())
		self.assertEqual(getdate(frappe.db.get_value("Operations", job.name, "delivery_date")), getdate(nowdate()))
		with self.assertRaises(frappe.ValidationError):
			job_360.record_delivery(job.name, add_days(nowdate(), 2))

	def test_extend_free_time(self):
		job = make(job_type="Import")
		job.atd_date = add_days(nowdate(), -5)
		job.ata_date = add_days(nowdate(), -3)
		job.free_time_days = 5
		job.save(ignore_permissions=True)
		until = add_days(nowdate(), 10)
		job_360.extend_free_time(job.name, until)
		job.reload()
		self.assertEqual(getdate(job.free_time_expiry), getdate(until))
		with self.assertRaises(frappe.ValidationError):
			job_360.extend_free_time(job.name, add_days(nowdate(), 1))
