# Copyright (c) 2026, DVNKS Systems and contributors
"""Sales Invoice rules for freight billing."""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.nestedset import get_ancestors_of

OVERSEAS_CUSTOMER_GROUP = "OVERSEAS"


def enforce_overseas_zero_rating(doc, method=None):
	"""An invoice for an overseas customer may not carry VAT.

	The Tax Rule added by the `create_overseas_tax_rule` patch selects the
	zero-rated template on its own; this stops someone swapping it for a
	VAT-bearing one by hand.
	"""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
		return

	group = doc.customer_group or frappe.db.get_value("Customer", doc.customer, "customer_group")
	if not is_overseas_group(group):
		return

	charged = [row for row in doc.get("taxes") or [] if flt(row.rate) or flt(row.tax_amount)]
	if not charged:
		return

	frappe.throw(
		_("{0} is an overseas customer, so this invoice must be zero-rated. Remove the VAT charged on: {1}.").format(
			frappe.bold(doc.customer_name or doc.customer),
			", ".join(frappe.bold(row.description or row.account_head) for row in charged),
		),
		title=_("Zero-rated customer"),
	)


def is_overseas_group(group):
	if not group:
		return False
	if group == OVERSEAS_CUSTOMER_GROUP:
		return True
	return OVERSEAS_CUSTOMER_GROUP in get_ancestors_of("Customer Group", group)
