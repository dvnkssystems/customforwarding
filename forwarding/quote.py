# Copyright (c) 2026, DVNKS Systems and contributors
"""Quote approval and validity (M-07, M-08).

A Quote is submittable: submitting it approves it and locks its prices
(Draft -> Submitted). Only a submitted quote whose validity has not passed
makes a job (`assert_can_make_job`, called by quote_to_job). Validity can still
be extended on a submitted quote (the field is allow_on_submit), which makes it
usable again.

`Quote` is a custom DocType with no controller class, so these run as
doc_events (hooks.py).
"""

import frappe
from frappe import _
from frappe.utils import formatdate, getdate, nowdate

STATUS_BY_DOCSTATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def is_expired(validity, today=None):
	"""True once the validity date is before today (the site's day, Asia/Riyadh).
	A quote with no validity never expires."""
	return bool(validity) and getdate(validity) < getdate(today or nowdate())


def set_status(doc, method=None):
	doc.status = STATUS_BY_DOCSTATUS.get(doc.docstatus, "Draft")


def before_submit(doc, method=None):
	"""Approving an expired quote would lock prices nobody can use."""
	if is_expired(doc.validity):
		frappe.throw(
			_("Quote {0} expired on {1}. Extend its validity before submitting it.").format(
				doc.name, formatdate(doc.validity)
			),
			title=_("Quote expired"),
		)
	doc.status = "Submitted"


def before_cancel(doc, method=None):
	doc.status = "Cancelled"


def assert_can_make_job(quote_name):
	"""Throw unless the quote is submitted and still valid."""
	quote = frappe.db.get_value("Quote", quote_name, ["name", "docstatus", "validity"], as_dict=True)
	if not quote:
		frappe.throw(_("Quote {0} not found").format(quote_name), frappe.DoesNotExistError)
	if quote.docstatus != 1:
		frappe.throw(
			_("Quote {0} is not submitted. Submit the quote before creating a job from it.").format(quote.name)
			if quote.docstatus == 0
			else _("Quote {0} is cancelled. Amend it to create a job.").format(quote.name),
			title=_("Quote not approved"),
		)
	if is_expired(quote.validity):
		frappe.throw(
			_("Quote {0} expired on {1}. Extend its validity before creating a job from it.").format(
				quote.name, formatdate(quote.validity)
			),
			title=_("Quote expired"),
		)
