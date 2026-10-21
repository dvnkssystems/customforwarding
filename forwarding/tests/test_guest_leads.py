# Copyright (c) 2026, DVNKS Systems and contributors
"""Guests cannot create Leads.

Production had Guest-owned Leads with scanner payloads in email_id. The Guest
route to a Lead is the website Contact Us endpoint (Frappe's, overridden by
ERPNext to insert a Lead + Opportunity). The close_guest_lead_paths patch
disables the page and the Lead creation; forwarding.contact_us guards the
endpoint itself. The public Freight Job Request form stays open and is
validated and rate-limited. Everything is rolled back.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.handler import execute_cmd
from frappe.tests import IntegrationTestCase

from forwarding import contact_us
from forwarding.patches.v1_0 import close_guest_lead_paths

SCANNER_EMAILS = ("sample@email.tst'\"", "%2527%2522\\'\\\"", "a@b.com, c@d.com", "Bob <bob@example.com>")
CONTACT_PATHS = ("frappe.www.contact.send_message", "erpnext.templates.utils.send_message")


def _lead_count():
	return frappe.db.count("Lead")


class TestGuestLeads(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._ip = getattr(frappe.local, "request_ip", None)
		self._request = getattr(frappe.local, "request", None)
		# Each test is its own "visitor" so per-IP rate limits never leak across tests.
		frappe.local.request_ip = "203.0.113.%d" % (abs(hash(self._testMethodName)) % 200 + 1)
		frappe.cache.delete_keys("rl:")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.request_ip = self._ip
		frappe.local.request = self._request
		frappe.form_dict.clear()
		frappe.cache.delete_keys("rl:")
		frappe.db.rollback()

	def _enable_contact_form(self, opportunity=True):
		frappe.db.set_single_value("Contact Us Settings", "is_disabled", 0)
		frappe.db.set_single_value("CRM Settings", "enable_opportunity_creation_from_contact_us", int(opportunity))
		frappe.clear_document_cache("Contact Us Settings", "Contact Us Settings")

	def _guest_call(self, cmd, **kwargs):
		"""Run `cmd` the way /api/method/<cmd> would for a Guest."""
		frappe.local.request = SimpleNamespace(method="POST", host=None, headers={})
		frappe.set_user("Guest")
		frappe.form_dict.clear()
		frappe.form_dict.update(kwargs)
		frappe.form_dict.cmd = cmd
		try:
			return execute_cmd(cmd)
		finally:
			frappe.set_user("Administrator")

	def test_patch_closes_contact_us_lead_path(self):
		self._enable_contact_form()
		close_guest_lead_paths.execute()
		close_guest_lead_paths.execute()  # idempotent
		frappe.clear_document_cache("Contact Us Settings", "Contact Us Settings")
		self.assertEqual(frappe.db.get_single_value("Contact Us Settings", "is_disabled"), 1)
		self.assertEqual(
			frappe.db.get_single_value("CRM Settings", "enable_opportunity_creation_from_contact_us"), 0
		)

	def test_both_contact_paths_are_overridden(self):
		hooks = frappe.get_hooks("override_whitelisted_methods")
		for path in CONTACT_PATHS:
			self.assertEqual(hooks[path][-1], "forwarding.contact_us.send_message")

	def test_guest_blocked_when_contact_form_disabled(self):
		self._enable_contact_form()
		close_guest_lead_paths.execute()
		frappe.clear_document_cache("Contact Us Settings", "Contact Us Settings")
		before = _lead_count()
		for path in CONTACT_PATHS:
			with self.assertRaises(frappe.PermissionError):
				self._guest_call(path, sender="guest@example.com", message="hello")
		self.assertEqual(_lead_count(), before)

	def test_guest_scanner_emails_rejected(self):
		self._enable_contact_form()
		before = _lead_count()
		for email in SCANNER_EMAILS:
			for path in CONTACT_PATHS:
				with self.assertRaises(frappe.InvalidEmailAddressError):
					self._guest_call(path, sender=email, message="hello")
		self.assertEqual(_lead_count(), before)
		self.assertFalse(frappe.db.exists("Lead", {"owner": "Guest"}))

	def test_enabled_form_still_works_with_valid_input(self):
		self._enable_contact_form()
		self._guest_call(
			"frappe.www.contact.send_message",
			sender="real.visitor@example.com",
			message="x" * (contact_us.MAX_MESSAGE + 500),
			subject="s" * 300,
		)
		lead = frappe.db.get_value("Lead", {"email_id": "real.visitor@example.com"}, "name")
		self.assertTrue(lead)
		comm = frappe.get_last_doc(
			"Communication", filters={"sender": "real.visitor@example.com", "reference_doctype": "Opportunity"}
		)
		self.assertLessEqual(len(comm.content), contact_us.MAX_MESSAGE)
		self.assertLessEqual(len(comm.subject), contact_us.MAX_SUBJECT)

	def test_contact_form_is_rate_limited(self):
		self._enable_contact_form(opportunity=False)
		with patch("erpnext.templates.utils.send_message") as inner:
			inner.__wrapped__ = lambda *a: None
			for _ in range(contact_us.RATE_LIMIT):
				self._guest_call("frappe.www.contact.send_message", sender="ok@example.com", message="hi")
			with self.assertRaises(frappe.RateLimitExceededError):
				self._guest_call("frappe.www.contact.send_message", sender="ok@example.com", message="hi")

	def test_guest_has_no_lead_permission(self):
		frappe.set_user("Guest")
		self.assertFalse(frappe.has_permission("Lead", "create"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Lead", "lead_name": "Scanner", "email_id": "x@example.com"}).insert()
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.PermissionError):
			self._guest_call("frappe.client.insert", doc={"doctype": "Lead", "lead_name": "Scanner"})

	def test_appointment_portal_is_off_for_guests(self):
		# ERPNext's Appointment creates a Lead for unknown emails; its Guest
		# endpoint must stay behind the (disabled) appointment portal setting.
		self.assertFalse(frappe.db.get_single_value("Appointment Booking Settings", "enable_appointment_portal"))
		before = _lead_count()
		with self.assertRaises(frappe.Redirect):
			self._guest_call(
				"erpnext.www.book_appointment.index.create_appointment",
				date="2030-01-01",
				time="10:00:00",
				tz="Asia/Riyadh",
				contact=frappe.as_json({"name": "Scan", "email": "scan@example.com"}),
			)
		self.assertEqual(_lead_count(), before)

	def test_no_guest_web_form_or_server_script_for_lead(self):
		self.assertFalse(
			frappe.get_all(
				"Web Form",
				filters={"doc_type": ["in", ["Lead", "Opportunity"]], "published": 1, "login_required": 0},
			)
		)
		self.assertFalse(
			frappe.get_all("Server Script", filters={"script_type": "API", "allow_guest": 1, "disabled": 0})
		)

	def test_job_request_rejects_bad_email_and_caps_text(self):
		with self.assertRaises(frappe.InvalidEmailAddressError):
			self._guest_call(
				"forwarding.api.submit_job_request",
				payload=frappe.as_json({"partner_company": "Scan", "partner_email": SCANNER_EMAILS[0]}),
			)
		with self.assertRaises(frappe.ValidationError):
			self._guest_call("forwarding.api.submit_job_request", payload="[1, 2]")

		with patch.object(frappe.db, "commit"):
			out = self._guest_call(
				"forwarding.api.submit_job_request",
				payload=frappe.as_json(
					{
						"partner_company": "c" * 400,
						"partner_email": "partner@example.com",
						"cargo_description": "d" * 5000,
						"weight": "12.5",
						"pieces": "3",
					}
				),
			)
		doc = frappe.get_doc("Freight Job Request", out["name"])
		self.assertEqual(len(doc.partner_company), 140)
		self.assertEqual(len(doc.cargo_description), 2000)
		self.assertEqual(doc.weight, 12.5)
		self.assertEqual(doc.pieces, 3)

	def test_job_request_is_rate_limited(self):
		payload = frappe.as_json({"partner_company": "Rate"})
		with patch.object(frappe.db, "commit"):
			for _ in range(10):
				self._guest_call("forwarding.api.submit_job_request", payload=payload)
			with self.assertRaises(frappe.RateLimitExceededError):
				self._guest_call("forwarding.api.submit_job_request", payload=payload)
