# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Vehicle: say which insurance date is missing (A-33).

ERPNext's Vehicle.validate compares the insurance dates with getdate(), which
reads a blank date as today: an End Date in the past with no Start Date said
"Insurance Start date should be less than Insurance End date". This runs on
before_validate, ahead of ERPNext's controller validate, and names the
missing date instead.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today


def before_validate(doc, method=None):
	if doc.get("end_date") and not doc.get("start_date"):
		frappe.throw(_("Enter the Insurance Start Date"), title=_("Insurance Start Date missing"))
	# A Start Date after today with no End Date trips the same check.
	if doc.get("start_date") and not doc.get("end_date") and getdate(doc.start_date) > getdate(today()):
		frappe.throw(_("Enter the Insurance End Date"), title=_("Insurance End Date missing"))
