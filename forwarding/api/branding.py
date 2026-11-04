# Copyright (c) 2026, DVNKS Systems and contributors
"""The site's name, logo and browser-tab icon, for the Vue app.

The app serves more than one client from the same build, so it asks the site
which company it is. Guests can read this: the login page shows the logo
before anyone signs in. Only what that page shows anyway is returned.
"""

import frappe


def _default_company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get():
	"""{"name", "logo", "icon"}: Website Settings first, else the default Company."""
	settings = frappe.db.get_value(
		"Website Settings", "Website Settings", ["app_name", "app_logo", "favicon"], as_dict=True
	) or frappe._dict()
	company = _default_company()
	company_logo = frappe.db.get_value("Company", company, "company_logo") if company else None
	app_name = settings.app_name if settings.app_name and settings.app_name != "Frappe" else None
	logo = settings.app_logo or company_logo or ""
	return {
		"name": app_name or company or "",
		"logo": logo,
		"icon": settings.favicon or "",
	}
