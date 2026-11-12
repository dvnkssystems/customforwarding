# Copyright (c) 2026, DVNKS Systems and contributors
"""User management for the app's Users screen (ONE Freight, 12 Nov).

An admin (System Manager) lists the staff logins, adds one, changes what it
may do, sets its password and switches it off. "What it may do" is an access
level, a bundle of roles from LEVELS, plus any EXTRA_ROLES ticked one by one.

Only the roles this module knows about (MANAGED) are ever added or removed;
anything else a user holds (given in desk, or by another app) is left alone.
Roles a site does not have are skipped, so the same levels work on every site.

Administrator and Guest are not listed or editable, and an admin cannot
switch themselves off or take away their own System Manager role, so the
site always keeps someone who can manage users.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, validate_email_address

ADMIN_ROLE = "System Manager"
HIDDEN_USERS = ("Administrator", "Guest")

# (key, label, what it gives, roles). Order matters: a user's level is the
# first one whose roles they all hold.
LEVELS = (
	(
		"admin",
		"Admin",
		"Everything, including users and settings.",
		(
			ADMIN_ROLE,
			"Freight Admin",
			"Freight Manager",
			"Operations",
			"Custom Clearance",
			"Accounts Manager",
			"Accounts User",
			"Sales Manager",
			"Sales User",
			"Sales Master Manager",
			"Purchase Manager",
			"Purchase User",
			"Purchase Master Manager",
			"Item Manager",
			"Stock Manager",
			"Stock User",
			"Fleet Manager",
			"Report Manager",
		),
	),
	(
		"accounts",
		"Accounts",
		"Invoices, payments, journal entries and statements, and the jobs they belong to.",
		("Accounts Manager", "Accounts User", "Freight Finance", "Purchase User", "Operations"),
	),
	(
		"operations",
		"Operations",
		"Jobs, customs clearance, quotations and vehicles; customers and suppliers read-only.",
		("Operations", "Custom Clearance", "Freight Operator", "Sales User", "Purchase User", "Stock User", "Fleet Manager"),
	),
	(
		"sales",
		"Sales",
		"Leads, quotations and customers.",
		("Sales Manager", "Sales User", "Sales Master Manager", "Freight Sales"),
	),
)

# Ticked one by one on top of a level.
EXTRA_ROLES = (
	("Auditor", "Read-only access to accounts"),
	("Report Manager", "Build and edit reports"),
	("Delivery Manager", "Manage deliveries and vehicles"),
	("Delivery User", "View deliveries"),
	("Jeddah operation staff", "Jeddah branch"),
	("Riyadh operation staff", "Riyadh branch"),
	("Dammam operation staff", "Dammam branch"),
)

MANAGED = tuple(dict.fromkeys([r for level in LEVELS for r in level[3]] + [r for r, _label in EXTRA_ROLES]))


def _only_admins():
	frappe.only_for(ADMIN_ROLE)


def _existing_roles():
	return set(frappe.get_all("Role", filters={"name": ["in", MANAGED], "disabled": 0}, pluck="name"))


def _level_roles(key, existing):
	for level in LEVELS:
		if level[0] == key:
			return [r for r in level[3] if r in existing]
	frappe.throw(_("Choose an access level."))


def level_of(roles, existing=None):
	"""Admin for any System Manager; otherwise the first level whose roles
	(those the site has) the user all holds; '' when none fits."""
	existing = _existing_roles() if existing is None else existing
	held = set(roles)
	if ADMIN_ROLE in held:
		return "admin"
	for key, _label, _desc, level_roles in LEVELS:
		wanted = {r for r in level_roles if r in existing}
		if wanted and wanted <= held:
			return key
	return ""


def has_outgoing_email():
	return bool(frappe.get_all("Email Account", filters={"enable_outgoing": 1}, limit=1))


@frappe.whitelist()
def get_options():
	_only_admins()
	existing = _existing_roles()
	return {
		"levels": [
			{"key": key, "label": label, "description": desc, "roles": [r for r in roles if r in existing]}
			for key, label, desc, roles in LEVELS
		],
		"extra_roles": [{"role": r, "label": label} for r, label in EXTRA_ROLES if r in existing],
		"can_email": has_outgoing_email(),
		"me": frappe.session.user,
	}


@frappe.whitelist()
def list_users():
	_only_admins()
	users = frappe.get_all(
		"User",
		filters={"user_type": "System User", "name": ["not in", HIDDEN_USERS]},
		fields=["name", "full_name", "first_name", "last_name", "email", "mobile_no", "enabled", "last_login", "creation"],
		order_by="enabled desc, full_name asc",
	)
	roles = {}
	for row in frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "parent": ["in", [u.name for u in users] or [""]]},
		fields=["parent", "role"],
	):
		roles.setdefault(row.parent, []).append(row.role)
	existing = _existing_roles()
	extra = {r for r, _label in EXTRA_ROLES}
	for u in users:
		held = roles.get(u.name, [])
		u.level = level_of(held, existing)
		u.extra_roles = sorted(r for r in held if r in extra)
		u.roles = sorted(held)
	return users


@frappe.whitelist()
def save_user(data):
	"""Create or update a user. `data`: name (blank for new), email, first_name,
	last_name, mobile_no, enabled, level, extra_roles[], password."""
	_only_admins()
	data = frappe._dict(frappe.parse_json(data) if isinstance(data, str) else data)
	existing = _existing_roles()
	target = set(_level_roles(data.level, existing))
	target |= {r for r in (data.extra_roles or []) if r in existing and r in MANAGED}
	password = cstr(data.password).strip()
	enabled = cint(data.get("enabled", 1))

	name = cstr(data.name).strip()
	if name in HIDDEN_USERS:
		frappe.throw(_("{0} cannot be changed here.").format(name))
	if name == frappe.session.user:
		if not enabled:
			frappe.throw(_("You cannot switch off your own login."))
		if ADMIN_ROLE not in target:
			frappe.throw(_("You cannot remove your own Admin access."))

	if name:
		user = frappe.get_doc("User", name)
	else:
		email = cstr(data.email).strip().lower()
		if not validate_email_address(email):
			frappe.throw(_("Enter a valid email address."))
		if frappe.db.exists("User", email):
			frappe.throw(_("A user with the email {0} already exists.").format(email))
		if not password and not has_outgoing_email():
			frappe.throw(_("Set a password: this site has no outgoing email to send a welcome link."))
		user = frappe.new_doc("User")
		user.email = email
		user.user_type = "System User"
		user.send_welcome_email = 0 if password else 1

	user.first_name = cstr(data.first_name).strip()
	if not user.first_name:
		frappe.throw(_("Enter a first name."))
	user.last_name = cstr(data.last_name).strip()
	user.mobile_no = cstr(data.mobile_no).strip()
	user.enabled = enabled
	if password:
		# Checked against the site's password policy when the user is saved.
		user.new_password = password

	held = {r.role for r in user.get("roles")}
	user.set("roles", [r for r in user.get("roles") if r.role not in MANAGED or r.role in target])
	for role in sorted(target - held):
		user.append("roles", {"role": role})

	if name:
		user.save(ignore_permissions=True)
	else:
		user.insert(ignore_permissions=True)
	return user.name


@frappe.whitelist()
def set_enabled(user, enabled):
	_only_admins()
	if user in HIDDEN_USERS:
		frappe.throw(_("{0} cannot be changed here.").format(user))
	enabled = cint(enabled)
	if user == frappe.session.user and not enabled:
		frappe.throw(_("You cannot switch off your own login."))
	doc = frappe.get_doc("User", user)
	doc.enabled = enabled
	doc.save(ignore_permissions=True)
	return doc.enabled


@frappe.whitelist()
def send_reset_link(user):
	_only_admins()
	if user in HIDDEN_USERS:
		frappe.throw(_("{0} cannot be changed here.").format(user))
	if not has_outgoing_email():
		frappe.throw(_("This site has no outgoing email. Set a new password instead."))
	frappe.get_doc("User", user).reset_password(send_email=True)
	return True
