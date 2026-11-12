# Copyright (c) 2026, DVNKS Systems and contributors
"""The app's Users screen backend (forwarding.user_admin)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import user_admin

EMAIL = "ua-test-user@example.com"
PASSWORD = "Fr8-Ua-Test-2026!x"


def make(level="operations", extra=None, **values):
	data = {"email": EMAIL, "first_name": "Test", "last_name": "User", "level": level, "extra_roles": extra or [], "password": PASSWORD}
	data.update(values)
	return user_admin.save_user(data)


class TestUserAdmin(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("User", EMAIL):
			frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
		self.existing = user_admin._existing_roles()

	def tearDown(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("User", EMAIL):
			frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)

	def roles(self):
		return set(frappe.get_roles(EMAIL))

	def test_create_gives_the_level_roles_and_extras(self):
		extra = [r for r in ("Auditor",) if r in self.existing]
		name = make(extra=extra)
		self.assertEqual(name, EMAIL)
		want = set(user_admin._level_roles("operations", self.existing)) | set(extra)
		self.assertTrue(want <= self.roles())
		row = next(u for u in user_admin.list_users() if u.name == EMAIL)
		self.assertEqual(row.level, "operations")
		self.assertEqual(row.extra_roles, sorted(extra))

	def test_changing_level_keeps_roles_this_screen_does_not_manage(self):
		make()
		user = frappe.get_doc("User", EMAIL)
		user.append("roles", {"role": "Blogger"})
		user.save(ignore_permissions=True)
		make(level="sales", name=EMAIL, password="")
		roles = self.roles()
		self.assertIn("Blogger", roles)
		only_ops = set(user_admin._level_roles("operations", self.existing)) - set(user_admin._level_roles("sales", self.existing))
		self.assertFalse(only_ops & roles)
		self.assertEqual(next(u for u in user_admin.list_users() if u.name == EMAIL).level, "sales")

	def test_disable_and_enable(self):
		make()
		user_admin.set_enabled(EMAIL, 0)
		self.assertEqual(frappe.db.get_value("User", EMAIL, "enabled"), 0)
		user_admin.set_enabled(EMAIL, 1)
		self.assertEqual(frappe.db.get_value("User", EMAIL, "enabled"), 1)

	def test_new_user_needs_a_password_without_outgoing_email(self):
		with patch.object(user_admin, "has_outgoing_email", return_value=False):
			self.assertRaises(frappe.ValidationError, make, password="")

	def test_only_admins(self):
		make(level="sales")
		frappe.set_user(EMAIL)
		self.assertRaises(frappe.PermissionError, user_admin.list_users)
		self.assertRaises(frappe.PermissionError, user_admin.get_options)

	def test_admin_cannot_lock_themselves_out(self):
		make(level="admin")
		frappe.set_user(EMAIL)
		self.assertRaises(frappe.ValidationError, user_admin.set_enabled, EMAIL, 0)
		self.assertRaises(frappe.ValidationError, make, level="sales", name=EMAIL, password="")

	def test_any_system_manager_reads_as_admin(self):
		self.assertEqual(user_admin.level_of(["System Manager", "Blogger"]), "admin")
		self.assertEqual(user_admin.level_of(["Blogger"]), "")

	def test_administrator_is_not_listed_or_editable(self):
		self.assertNotIn("Administrator", [u.name for u in user_admin.list_users()])
		self.assertRaises(frappe.ValidationError, user_admin.set_enabled, "Administrator", 0)
