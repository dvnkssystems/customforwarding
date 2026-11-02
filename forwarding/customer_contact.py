# Copyright (c) 2026, DVNKS Systems and contributors
"""A customer's contact email, captured when the customer is created (B3-15).

ERPNext keeps a customer's email on its primary Contact; Customer.email_id is
read-only and filled from that contact. The app's New Customer form has an
Email box (`contact_email`, shown only on a new customer). On insert it is
handed to `email_id`, and ERPNext's own Customer.create_primary_contact (run
on save) makes the primary Contact with it. The invoice email's To is then
filled from it (job360.customerEmail). Optional: a customer may have none.
"""

import frappe
from frappe.utils import validate_email_address


def set_primary_contact_email(doc, method=None):
	email = (doc.get("contact_email") or "").strip()
	if not email or doc.get("email_id"):
		return
	doc.email_id = validate_email_address(email, throw=True)
