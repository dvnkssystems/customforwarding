# Copyright (c) 2026, DVNKS Systems and contributors
"""Close the Guest -> Lead path through the website Contact Us form.

Production had Guest-owned Leads with scanner payloads in email_id. The only
Guest route to a Lead on this stack is the Contact Us endpoint
(frappe.www.contact.send_message, overridden by ERPNext to create a Lead and
Opportunity). Nobody uses the page: Contact Us Settings has no address, email
or forward-to address, and the Vue portal does not call it.

- Contact Us Settings.is_disabled -> 1. The DocType default is 1, but the
  value was never saved, so it read as 0 and the page and endpoint were live.
- CRM Settings.enable_opportunity_creation_from_contact_us -> 0, so the Lead
  insert stays off even if someone re-enables the page.

Also removes any Guest create/write rights on Lead (Custom DocPerm) should a
site have added them. Site records only; idempotent.
"""

import frappe


def execute():
	frappe.db.set_single_value("Contact Us Settings", "is_disabled", 1)
	frappe.db.set_single_value("CRM Settings", "enable_opportunity_creation_from_contact_us", 0)

	for doctype in ("Lead", "Opportunity"):
		frappe.db.delete("Custom DocPerm", {"parent": doctype, "role": "Guest"})
		frappe.clear_cache(doctype=doctype)
