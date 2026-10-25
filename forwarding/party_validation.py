# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Number-only party fields (R3-41).

The Saudi Commercial Registration number (CR No) is exactly 10 digits. Checked
on a new customer and whenever the CR No is changed, so a customer saved
earlier with a placeholder still saves until someone edits the number.
"""

import frappe
from frappe import _

CR_DIGITS = 10


def validate_cr_no(doc, method=None):
	if not doc.meta.has_field("cr_no"):
		return
	number = "".join((doc.get("cr_no") or "").split())
	doc.cr_no = number or None
	if not number:
		return
	if len(number) == CR_DIGITS and number.isdigit() and number.isascii():
		return
	before = doc.get_doc_before_save() if not doc.is_new() else None
	if before and "".join((before.get("cr_no") or "").split()) == number:
		return
	frappe.throw(
		_("{0} must be exactly {1} digits.").format(_(doc.meta.get_label("cr_no")), CR_DIGITS),
		title=_("Invalid CR No"),
	)
