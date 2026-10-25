# Copyright (c) 2026, DVNKS Systems and contributors
"""The P0 items of the Phase 1 corrections review (C1–C3).

C4 (free time left) needed no change: days left is computed at read time;
the reported values were a Riyadh-vs-IST date boundary, not a stored value.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import party_360
from forwarding.api import job_360
from forwarding.forwarding.doctype.operations.operations import make_sales_invoice
from forwarding.quote_to_job import _resolve_port, _set_direction
from forwarding.tests.test_job_360 import ensure_submitted
from forwarding.tests.test_job_360_p2 import job_with_rows, make_clearance, make_transportation


class P0TestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)

	# C1 — invoices raised from a job ------------------------------------------

	def test_job_gets_a_project_named_after_it(self):
		job = job_with_rows()
		job.reload()
		self.assertEqual(job.project, job.name)
		self.assertTrue(frappe.db.exists("Project", job.name))

	def test_existing_project_is_kept(self):
		job = job_with_rows()
		job.reload()
		job.ensure_project()
		self.assertEqual(frappe.db.count("Project", {"name": job.name}), 1)

	def test_mapped_invoice_is_dated_today_and_numbered_as_an_invoice(self):
		job = job_with_rows(date=add_days(nowdate(), -30))
		frappe.db.set_value("Operations", job.name, "posting_date", add_days(nowdate(), -30))
		ensure_submitted(job.name)
		si = make_sales_invoice(job.name)
		self.assertEqual(str(si.posting_date), nowdate())
		self.assertGreaterEqual(str(si.due_date), nowdate())
		self.assertNotIn("branch_abb", si.naming_series or "")
		self.assertEqual(si.operations, job.name)

	# C2 — documents counted once per job --------------------------------------

	def test_linked_copies_do_not_inflate_document_counts(self):
		job = job_with_rows()
		before = job_360.build(job.name)["kpis"]
		make_transportation(job)
		make_clearance(job)
		frappe.cache.delete_keys("job_360")
		payload = job_360.build(job.name)
		kpis = payload["kpis"]
		self.assertEqual((kpis["docs_received"], kpis["docs_total"]), (before["docs_received"], before["docs_total"]))
		self.assertEqual(len(payload["documents"]), before["docs_total"])
		self.assertEqual(len(kpis["pending_documents"]), before["docs_total"] - before["docs_received"])
		customs = [d for d in payload["documents"] if d["stage"] == "Customs Clearance"][0]
		self.assertEqual(customs["source_doctype"], "Operations")
		self.assertGreater(len(customs["sources"]), 1)

	def test_received_on_any_copy_counts(self):
		rows = [
			{"document": "SABER", "stage": "Documentation", "received": 0, "date": None, "attach": None,
			 "source_doctype": "Operations", "source_name": "J1", "row_name": "a"},
			{"document": "SABER", "stage": "Documentation", "received": 1, "date": nowdate(), "attach": "/f.pdf",
			 "source_doctype": "Transportation", "source_name": "T1", "row_name": "b"},
			{"document": None, "stage": None, "received": 0, "date": None, "attach": None,
			 "source_doctype": "Operations", "source_name": "J1", "row_name": "c"},
			{"document": None, "stage": None, "received": 0, "date": None, "attach": None,
			 "source_doctype": "Operations", "source_name": "J1", "row_name": "d"},
		]
		merged = party_360.merge_documents(rows, lambda _r: "J1")
		self.assertEqual(len(merged), 3)
		self.assertEqual((merged[0]["received"], merged[0]["attach"], merged[0]["row_name"]), (1, "/f.pdf", "a"))
		self.assertEqual([s["source_doctype"] for s in merged[0]["sources"]], ["Operations", "Transportation"])

	# C3 — quote details onto the job ------------------------------------------

	def _port(self, code, name, mode, country):
		doc = frappe.get_doc(
			{"doctype": "Port", "port_code": code, "port_name": name, "mode_of_shipment": mode, "country": country}
		)
		return doc.insert(ignore_permissions=True, ignore_if_duplicate=True).name

	def test_port_resolves_by_mode_and_quality(self):
		sea = self._port("ZZSEA", "Testhaven", "Sea", "Saudi Arabia")
		air = self._port("ZZA", "Testhaven", "Air", "Saudi Arabia")
		self._port("port_code", "Testhaven", "Sea", "All Territories")
		self.assertEqual(_resolve_port("Testhaven", "Sea"), sea)
		self.assertEqual(_resolve_port("Testhaven", "Air"), air)
		self.assertIsNone(_resolve_port("Nowhere-at-all", "Sea"))

	def test_direction_from_saudi_destination(self):
		origin = self._port("ZZORI", "Testorigin", "Sea", "Germany")
		branch = frappe.get_all("Branch", filters={"name": ["!=", "ALL"]}, pluck="name", limit=1)[0]
		destination = self._port("ZZDST", branch.title(), "Sea", "Saudi Arabia")
		target = frappe._dict(port_of_loading=origin, port_of_destination=destination)
		_set_direction(target, "Sea")
		self.assertEqual(target.job_type, "Import")
		self.assertEqual(target.branch, branch)
