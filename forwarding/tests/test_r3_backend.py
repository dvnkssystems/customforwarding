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


class TestPublicShare(R3BackendCase):
	# R3-51 --------------------------------------------------------------------

	def invoice(self):
		name = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
		if not name:
			self.skipTest("no submitted Sales Invoice on this site")
		return name

	def page(self, token):
		from forwarding.www import invoice as page

		frappe.form_dict.token = token
		try:
			context = page.get_context(frappe._dict())
		finally:
			frappe.form_dict.pop("token", None)
		return context

	def test_section_is_hidden_and_off_by_default(self):
		meta = frappe.get_meta("Sales Invoice")
		for fieldname in ("flcs_share_section", "is_public", "public_token", "public_link", "public_link_expires_on"):
			self.assertTrue(meta.get_field(fieldname).hidden, fieldname)
		self.assertEqual(meta.get_field("is_public").default, "0")

	def test_only_an_admin_shares(self):
		from forwarding.api import share_invoice

		name = self.invoice()
		user = frappe.db.get_value("Has Role", {"role": "Accounts User", "parenttype": "User", "parent": ["not in", ["Administrator"]]}, "parent")
		if not user or {"System Manager", "Freight Admin"} & set(frappe.get_roles(user)):
			self.skipTest("no non-admin accounts user")
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			share_invoice(name)

	def test_link_expires(self):
		from frappe.utils import add_days, now_datetime

		from forwarding.api import share_invoice, unshare_invoice

		name = self.invoice()
		out = share_invoice(name, days=3)
		self.assertTrue(out["expires_on"])
		self.assertEqual(self.page(out["public_token"]).invoice.name, name)

		frappe.db.set_value("Sales Invoice", name, "public_link_expires_on", add_days(now_datetime(), -1))
		self.assertIsNone(self.page(out["public_token"]).invoice)

		out = share_invoice(name)
		unshare_invoice(name)
		self.assertIsNone(self.page(out["public_token"]).invoice)
