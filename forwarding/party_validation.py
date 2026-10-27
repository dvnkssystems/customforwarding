# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Number-only party fields (R3-41).

The Saudi Commercial Registration number (CR No) is exactly 10 digits. Checked
on a new customer or supplier and whenever the CR No is changed, so a party
saved earlier with a placeholder still saves until someone edits the number.
Only a Saudi party has a Saudi CR: one in the OVERSEAS group, or in another
country, is not checked (Simran, 27 Oct).
"""

import frappe
from frappe import _
from frappe.utils.nestedset import get_ancestors_of

CR_DIGITS = 10
HOME_COUNTRY = "Saudi Arabia"
OVERSEAS_GROUP = "OVERSEAS"
GROUP_FIELD = {"Customer": ("customer_group", "Customer Group"), "Supplier": ("supplier_group", "Supplier Group")}


def is_overseas_party(doc):
	"""In the OVERSEAS group (or under it), or in a country other than Saudi
	Arabia — the party's own country field, else its addresses'."""
	field, group_doctype = GROUP_FIELD.get(doc.doctype, (None, None))
	group = doc.get(field) if field else None
	if group and (group == OVERSEAS_GROUP or OVERSEAS_GROUP in get_ancestors_of(group_doctype, group)):
		return True
	countries = [doc.get("country")] if doc.get("country") else []
	if not countries and not doc.is_new():
		addresses = frappe.get_all(
			"Dynamic Link",
			filters={"link_doctype": doc.doctype, "link_name": doc.name, "parenttype": "Address"},
			pluck="parent",
		)
		countries = [c for c in (frappe.db.get_value("Address", a, "country") for a in addresses) if c]
	return bool(countries) and HOME_COUNTRY not in countries


def validate_cr_no(doc, method=None):
	if not doc.meta.has_field("cr_no"):
		return
	number = "".join((doc.get("cr_no") or "").split())
	doc.cr_no = number or None
	if not number or is_overseas_party(doc):
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
