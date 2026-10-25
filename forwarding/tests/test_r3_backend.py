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


def clearance(**values):
	from forwarding.tests.test_job_360 import make

	job = make()
	return frappe.get_doc({"doctype": "Custom Clearance", "operations": job.name, "clearance_status": "Draft", **values}).insert(
		ignore_permissions=True
	)


class TestNumberOnlyFields(R3BackendCase):
	# R3-41 --------------------------------------------------------------------

	def test_bayan_no_is_digits_only(self):
		cc = clearance()
		cc.reload()
		cc.bayyan_number = "effdq"
		with self.assertRaisesRegex(frappe.ValidationError, "Bayan No. must contain digits only"):
			cc.save()
		cc.reload()
		cc.bayyan_number = " 1234 5678 "
		cc.save()
		self.assertEqual(cc.bayyan_number, "12345678")

	def test_old_placeholder_bayan_still_saves(self):
		cc = clearance()
		frappe.db.set_value("Custom Clearance", cc.name, "bayyan_number", "OLD-1")
		cc.reload()
		cc.do_number = "DO-1"
		cc.save()

	def test_cr_no_is_ten_digits(self):
		from forwarding.tests.test_customer_360 import make_customer

		for bad in ("12345T6Y", "123456789", "12345678901"):
			with self.assertRaisesRegex(frappe.ValidationError, "CR No must be exactly 10 digits"):
				make_customer(cr_no=bad, custom_vat_registration_number="300000000000003")
		customer = make_customer(cr_no="1010999999", custom_vat_registration_number="300000000000003")
		customer.cr_no = "2050 064692"
		customer.save()
		self.assertEqual(customer.cr_no, "2050064692")


class TestServiceStatusSteps(R3BackendCase):
	# R3-39 --------------------------------------------------------------------

	def test_clearance_moves_one_step_at_a_time(self):
		from frappe.utils import nowdate

		from forwarding.api.service_status import get_status, set_status

		cc = clearance()
		state = get_status("Custom Clearance", cc.name)
		self.assertEqual(
			(state["status"], state["next_status"], state["next_label"]),
			("Draft", "Submitted to Customs", "Submit to Customs"),
		)
		self.assertEqual([f["fieldname"] for f in state["next_needs"]], ["bayyan_number", "bayyan_date"])
		self.assertEqual([e["status"] for e in state["extra"]], ["Rejected"])

		with self.assertRaisesRegex(frappe.ValidationError, "it can only move to"):
			set_status("Custom Clearance", cc.name, "Released")
		with self.assertRaisesRegex(frappe.MandatoryError, "Submit to Customs needs Bayan No., Bayan Date"):
			set_status("Custom Clearance", cc.name, "Submitted to Customs")
		with self.assertRaisesRegex(frappe.ValidationError, "digits only"):
			set_status("Custom Clearance", cc.name, "Submitted to Customs", {"bayyan_number": "abc", "bayyan_date": nowdate()})
		with self.assertRaisesRegex(frappe.ValidationError, "does not set do_number"):
			set_status("Custom Clearance", cc.name, "Submitted to Customs", {"do_number": "1"})

		state = set_status(
			"Custom Clearance", cc.name, "Submitted to Customs", {"bayyan_number": "123456", "bayyan_date": nowdate()}
		)
		self.assertEqual((state["status"], state["next_label"]), ("Submitted to Customs", "Mark Under Review"))
		self.assertEqual(frappe.db.get_value("Custom Clearance", cc.name, "bayyan_number"), "123456")
		self.assertEqual(set_status("Custom Clearance", cc.name, "Under Review")["next_label"], "Mark Duty Assessed")
		self.assertEqual(set_status("Custom Clearance", cc.name, "Duty Assessed")["next_label"], "Mark Released")
		state = set_status("Custom Clearance", cc.name, "Released")
		self.assertEqual((state["status"], state["next_status"], state["extra"]), ("Released", None, []))
		self.assertTrue(frappe.db.get_value("Custom Clearance", cc.name, "clearance_date"))

	def test_rejected_from_draft_then_submitted_again(self):
		from frappe.utils import nowdate

		from forwarding.api.service_status import set_status

		cc = clearance()
		state = set_status("Custom Clearance", cc.name, "Rejected")
		self.assertEqual((state["status"], state["next_status"]), ("Rejected", "Submitted to Customs"))
		state = set_status(
			"Custom Clearance", cc.name, "Submitted to Customs", {"bayyan_number": "77", "bayyan_date": nowdate()}
		)
		self.assertEqual(state["status"], "Submitted to Customs")

	def test_transportation_steps(self):
		from forwarding.api.service_status import set_status
		from forwarding.tests.test_job_360 import make

		job = make()
		tt = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		state = set_status("Transportation", tt.name, "In Transit")
		self.assertEqual((state["status"], state["next_label"]), ("In Transit", "Mark Delivered"))
		state = set_status("Transportation", tt.name, "Delivered")
		self.assertEqual((state["next_status"], [e["label"] for e in state["extra"]]), (None, ["Mark Container Returned"]))
		self.assertTrue(frappe.db.get_value("Transportation", tt.name, "delivery_date"))
		self.assertEqual(set_status("Transportation", tt.name, "Container Returned")["extra"], [])
