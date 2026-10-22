# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Supplier rules (Phase 2 spec §5.1).

Tax ID is mandatory only for Saudi suppliers: an overseas supplier has no
Saudi VAT number. The form shows it through the Tax ID field's
mandatory_depends_on (custom/supplier.json); Frappe only checks that in the
browser, so the same rule is enforced here for every other way in (API,
the Vue app, imports).
"""

import frappe
from frappe import _

TAX_ID_COUNTRY = "Saudi Arabia"


def validate(doc, method=None):
	if doc.get("country") == TAX_ID_COUNTRY and not (doc.get("tax_id") or "").strip():
		frappe.throw(
			_("Tax ID is mandatory for a supplier in {0}").format(_(TAX_ID_COUNTRY)),
			frappe.MandatoryError,
			title=_("Missing Tax ID"),
		)
