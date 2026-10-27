# Copyright (c) 2026, DVNKS Systems and contributors
"""Rows tied to a container, so picking its card filters the job page (A-23)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from forwarding.api import job_360
from forwarding.tests.test_job_360 import make

NUMBER = "MSCU2016911"


class TestUnits(IntegrationTestCase):
	def test_rows_and_legs_tagged_with_their_container(self):
		job = make(mode_of_shipment="Sea")
		job.append("container_details", {"container_no": NUMBER})
		kinds = frappe.get_all("Document List", pluck="name", limit=2)
		doc_type = len(kinds) == 2
		if doc_type:
			job.append("document_table", {"document": kinds[0], "unit": NUMBER.lower()})
			job.append("document_table", {"document": kinds[1]})
		job.flags.ignore_mandatory = True
		job.save(ignore_permissions=True)
		job.reload()
		legs = [l for l in job.get("transport_container_legs") or [] if l.reference_no == NUMBER]
		if legs:
			legs[0].pull_out = nowdate()
			job.save(ignore_permissions=True)

		payload = job_360.build(job.name)
		(unit,) = [u for u in payload["units"] if u["label"] == NUMBER]
		if doc_type:
			tagged = [d["unit"] for d in payload["documents"]]
			self.assertIn(unit["key"], tagged)
			self.assertIn(None, tagged)
		if legs:
			pulled = [m for m in payload["milestones"] if m.get("unit") == unit["key"] and m["key"].startswith("pull_out")]
			self.assertEqual(pulled[0]["status"], "done")
