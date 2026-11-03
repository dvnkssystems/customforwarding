# Copyright (c) 2026, DVNKS Systems and contributors
"""The go-live clean-up (forwarding.golive). Limited to the records each test
makes, with commits blocked, so the local data stays; rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import golive
from forwarding.patches.v1_0 import ofs1_retest2
from forwarding.tests.test_customer_360 import make_customer
from forwarding.tests.test_job_360 import make


class TestGoLive(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for target in ("frappe.model.document.run_server_script_for_doc_event", "frappe.db.commit"):
			patcher = patch(target)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.company = frappe.db.get_value("Company", {}, "name")
		customer = make_customer(cr_no="1010101010")
		job = make(customer=customer.name)
		transport = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		self.made = {"Customer": {customer.name}, "Operations": {job.name}, "Transportation": {transport.name}}
		self.made["Project"] = set(frappe.get_all("Project", filters={"customer": customer.name}, pluck="name"))
		with patch.object(ofs1_retest2, "COMPANY", self.company):
			ofs1_retest2.add_sample_fleet()

	def run_clean(self, confirm):
		real = golive.all_names
		mine = lambda doctype: [n for n in real(doctype) if n in self.made.get(doctype, ())]  # noqa: E731
		with (
			patch.object(golive, "COMPANY", self.company),
			patch.object(golive, "all_names", mine),
			patch.object(golive, "party_records", lambda doctype: []),
		):
			golive.clean_test_data(confirm=confirm)

	def exists(self):
		return {dt: [n for n in names if frappe.db.exists(dt, n)] for dt, names in self.made.items()}

	def test_trial_run_changes_nothing(self):
		before = self.exists()
		self.run_clean(None)
		self.assertEqual(self.exists(), before)
		self.assertTrue(frappe.db.exists("Vehicle", ofs1_retest2.SAMPLE_PLATE))

	def test_clears_test_data_and_sample_fleet(self):
		self.run_clean(self.company)
		self.assertEqual({dt: n for dt, n in self.exists().items() if n}, {})
		self.assertFalse(frappe.db.exists("Vehicle", ofs1_retest2.SAMPLE_PLATE))
		self.assertFalse(frappe.db.exists("Driver", {"full_name": ofs1_retest2.SAMPLE_DRIVER}))

	def test_other_sites_untouched(self):
		with patch.object(golive, "COMPANY", "No Such Company"):
			golive.clean_test_data(confirm="No Such Company")
		self.assertTrue(all(self.exists().values()))
