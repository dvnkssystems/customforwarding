# Copyright (c) 2026, DVNKS Systems and contributors
"""Arrival never before departure (A-25)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding.tests.test_job_360 import make


class TestDateOrder(IntegrationTestCase):
	def test_eta_before_etd_is_refused(self):
		job = make()
		job.etd_date = add_days(nowdate(), 10)
		job.eta_date = add_days(nowdate(), 8)
		with self.assertRaises(frappe.ValidationError) as caught:
			job.save(ignore_permissions=True)
		self.assertIn("cannot be before", str(caught.exception))

	def test_ata_before_atd_is_refused(self):
		job = make()
		job.atd_date = nowdate()
		job.ata_date = add_days(nowdate(), -2)
		with self.assertRaises(frappe.ValidationError):
			job.save(ignore_permissions=True)

	def test_same_day_is_fine(self):
		job = make()
		job.etd_date = job.eta_date = add_days(nowdate(), 5)
		job.save(ignore_permissions=True)

	def test_old_dates_nobody_touched_still_save(self):
		job = make()
		frappe.db.set_value("Operations", job.name, {"etd_date": add_days(nowdate(), 10), "eta_date": add_days(nowdate(), 8)})
		job.reload()
		job.po_no = "PO-1"
		job.save(ignore_permissions=True)
