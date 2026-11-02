# Copyright (c) 2026, DVNKS Systems and contributors
"""Invoice form clean-up (R3 item 17, A-06; Simran, 28 Oct and 2 Nov).

- Sales Invoice: hide the Public Share section, Update Cost, Include Payment
  (POS) and Title. Debit To offers receivable accounts only.
- Purchase Invoice: hide Credit To; it is always the supplier's payable
  (forwarding.party_accounts).
- Selling price list Standard Selling instead of "Selling Empty".
- The "Make QR Code" button goes from the client's Sales Invoice Client
  Script: the ZATCA QR is made on submit.
"""

import json
import re

import frappe

from forwarding.patches.v1_0.a14_hide_stock_fields_on_bills import set_property

HIDDEN = {
	"Sales Invoice": ["flcs_share_section", "update_cost", "is_pos", "title"],
	"Purchase Invoice": ["credit_to"],
}
DEBIT_TO_FILTERS = [["Account", "account_type", "=", "Receivable"], ["Account", "is_group", "=", 0]]
QR_BUTTON = re.compile(
	r"frappe\.ui\.form\.on\(\s*[\"']Sales Invoice[\"']\s*,\s*\{\s*refresh\s*\(\s*frm\s*\)\s*\{\s*"
	r"frm\.add_custom_button\(\s*__\(\s*[\"']Make QR Code[\"']\s*\).*?\n\}\);?[ \t]*\n?",
	re.S,
)


def execute():
	for doctype, fields in HIDDEN.items():
		meta = frappe.get_meta(doctype)
		for fieldname in fields:
			if meta.get_field(fieldname):
				set_property(doctype, fieldname, "hidden", 1)
		frappe.clear_cache(doctype=doctype)

	set_link_filters("Sales Invoice", "debit_to", DEBIT_TO_FILTERS)

	if frappe.db.exists("Price List", {"name": "Standard Selling", "selling": 1, "enabled": 1}):
		frappe.db.set_single_value("Selling Settings", "selling_price_list", "Standard Selling")
		frappe.db.set_default("selling_price_list", "Standard Selling")

	remove_qr_button()


def set_link_filters(doctype, fieldname, filters):
	value = json.dumps(filters)
	existing = frappe.db.get_value(
		"Property Setter", {"doc_type": doctype, "field_name": fieldname, "property": "link_filters"}
	)
	if existing:
		frappe.db.set_value("Property Setter", existing, "value", value)
	else:
		frappe.make_property_setter(
			{
				"doctype": doctype,
				"fieldname": fieldname,
				"property": "link_filters",
				"value": value,
				"property_type": "JSON",
			},
			validate_fields_for_doctype=False,
		)
	frappe.clear_cache(doctype=doctype)


def remove_qr_button():
	for name, script in frappe.get_all(
		"Client Script", filters={"dt": "Sales Invoice", "script": ["like", "%Make QR Code%"]}, fields=["name", "script"], as_list=True
	):
		cleaned = QR_BUTTON.sub("", script)
		if cleaned != script:
			frappe.db.set_value("Client Script", name, "script", cleaned)
