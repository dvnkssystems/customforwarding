# Copyright (c) 2026, DVNKS Systems and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.forwarding.doctype.party_alert_settings.party_alert_settings import DEFAULTS, get_settings


class IntegrationTestPartyAlertSettings(IntegrationTestCase):
	def test_defaults_and_overrides(self):
		# Never saved: every value is its default.
		frappe.db.delete("Singles", {"doctype": "Party Alert Settings"})
		self.assertEqual(get_settings(), DEFAULTS)

		settings = frappe.get_single("Party Alert Settings")

		settings.cost_variance_threshold = 12.5
		settings.rate_expiry_days = 10
		settings.save(ignore_permissions=True)
		got = get_settings()
		self.assertEqual((got.cost_variance_threshold, got.rate_expiry_days), (12.5, 10))

	def test_negative_rejected(self):
		settings = frappe.get_single("Party Alert Settings")
		settings.rate_expiry_days = -1
		self.assertRaises(frappe.ValidationError, settings.save, ignore_permissions=True)
