# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 corrections, sections 6-8: Transportation / Custom Clearance,
Quote, invoice and customer. Uses the site's own masters; everything is
rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase


class R3BackendCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)


class TestIndiaFieldsHidden(R3BackendCase):
	# R3-50 --------------------------------------------------------------------

	def test_gst_category_and_eway_bill_are_hidden(self):
		for doctype, fieldname in (("Customer", "gst_category"), ("Sales Invoice", "ewaybill")):
			field = frappe.get_meta(doctype).get_field(fieldname)
			if field:
				self.assertTrue(field.hidden, f"{doctype}.{fieldname} should be hidden")
