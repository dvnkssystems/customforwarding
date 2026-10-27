# Copyright (c) 2026, DVNKS Systems and contributors
"""A cut-off can be ticked Done on its own; ATD ticks them all (Simran, 27 Oct)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding.api import job_360
from forwarding.tests.test_job_360 import make


class TestCutoffDone(IntegrationTestCase):
	def setUp(self):
		self.job = make(job_type="Export", mode_of_shipment="Sea")
		if not self.job.get("cutoffs"):
			self.job.append("cutoffs", {"milestone": "SI Deadline", "deadline": add_days(nowdate(), -1)})
			self.job.save(ignore_permissions=True)
		self.row = self.job.cutoffs[0]

	def test_tick_one_row_done(self):
		out = job_360.set_cutoff_done(self.job.name, self.row.name, 1)
		self.assertEqual(out, {"is_done": 1, "cutoff_status": "Done"})
		job = frappe.get_doc("Operations", self.job.name)
		self.assertEqual(job.cutoffs[0].is_done, 1)
		# The other rows are untouched.
		self.assertTrue(all(not r.is_done for r in job.cutoffs[1:]))

	def test_untick(self):
		job_360.set_cutoff_done(self.job.name, self.row.name, 1)
		out = job_360.set_cutoff_done(self.job.name, self.row.name, 0)
		self.assertEqual(out["is_done"], 0)
		self.assertNotEqual(out["cutoff_status"], "Done")

	def test_atd_ticks_every_row(self):
		job = frappe.get_doc("Operations", self.job.name)
		job.etd_date = job.etd_date or nowdate()
		job.atd_date = nowdate()
		job.flags.ignore_mandatory = True
		job.save(ignore_permissions=True)
		job.reload()
		self.assertTrue(all(r.is_done and r.cutoff_status == "Done" for r in job.cutoffs))
