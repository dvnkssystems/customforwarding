# Copyright (c) 2026, DVNKS Systems and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.tests.test_job_360 import make as make_job


def make(*scopes, **values):
	"""A job holding these Scopes of Work (names), in its Scope Of Work table."""
	scopes = scopes or (frappe.get_all("Scope Of Work", pluck="name", order_by="name", limit=1)[0],)
	return make_job(scopes_of_work=[{"scope_of_work": s} for s in scopes], **values)


class TestJobScopeOfWork(IntegrationTestCase):
	def test_rows_keep_their_order(self):
		names = frappe.get_all("Scope Of Work", pluck="name", order_by="name", limit=2)
		job = make(*reversed(names))
		self.assertEqual([r.scope_of_work for r in job.scopes_of_work], list(reversed(names)))
		self.assertEqual(job.scope_of_work, names[-1])
		self.assertEqual(job.scopes_of_work[0].doctype, "Job Scope Of Work")
