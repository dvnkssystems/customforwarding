# Copyright (c) 2026, DVNKS Systems and contributors
"""Guarded replacement for the website "Contact Us" endpoint.

Frappe's `frappe.www.contact.send_message` is a Guest endpoint, and ERPNext
overrides it with `erpnext.templates.utils.send_message`, which also creates a
Lead and an Opportunity for the sender when CRM Settings > "Enable Opportunity
Creation from Contact Us" is on. ERPNext's version keeps going after Frappe's
"Contact Us Settings is disabled" early return, so with the page disabled a
Guest could still reach the Lead insert. That is how scanners left Guest-owned
Leads with junk email addresses on production.

Both dotted paths are pointed here through `override_whitelisted_methods`.
This version refuses outright while the Contact Us page is disabled, checks
the sender is exactly one valid email address, caps the subject and message
length, rate-limits per IP, and only then hands over to ERPNext's own logic
so an enabled contact form behaves as before.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cstr, validate_email_address

MAX_SUBJECT = 140
MAX_MESSAGE = 5000
RATE_LIMIT = 5
RATE_WINDOW = 10 * 60  # seconds


def contact_form_enabled() -> bool:
	return not frappe.get_single("Contact Us Settings").is_disabled


def clean_sender(sender) -> str:
	sender = cstr(sender).strip()
	if not sender or len(sender) > MAX_SUBJECT:
		frappe.throw(_("Please enter a valid email address."), frappe.InvalidEmailAddressError)
	email = validate_email_address(sender, throw=True)
	if not email or "," in email or email != sender:
		frappe.throw(_("Please enter a single valid email address."), frappe.InvalidEmailAddressError)
	return email


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=RATE_LIMIT, seconds=RATE_WINDOW)
def send_message(sender: str, message: str, subject: str = "Website Query"):
	if not contact_form_enabled():
		frappe.throw(_("The contact form is not available."), frappe.PermissionError)

	sender = clean_sender(sender)
	message = cstr(message).strip()[:MAX_MESSAGE]
	subject = cstr(subject).strip()[:MAX_SUBJECT] or "Website Query"
	if not message:
		frappe.throw(_("Please enter a message."))

	from erpnext.templates.utils import send_message as erpnext_send_message

	# Skip ERPNext's own rate limit wrapper: this endpoint already applied one.
	handler = getattr(erpnext_send_message, "__wrapped__", erpnext_send_message)
	return handler(sender, message, subject)
