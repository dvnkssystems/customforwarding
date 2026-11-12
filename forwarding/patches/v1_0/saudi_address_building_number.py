# Copyright (c) 2026, DVNKS Systems and contributors
"""Saudi addresses print the building number, and the district once
(ONE Freight, 11 Nov).

The site's "Saudi Arabia" Address Template (from KSA Compliance's setup, kept
in the DB) never printed Building Number, which ZATCA needs for B2B buyers,
and printed Area after the city, so a district typed in both Address Line 2
and Area showed twice: "King Fahd Road, Al Olaya, Riyadh, Al Olaya, 12214".
It now prints the national address order:

	Building No. 7421, King Fahd Road
	Al Olaya
	Riyadh 12214
	Saudi Arabia

A template that already prints the building number was edited by hand and is
left alone. Draft Sales Invoices and Customer.primary_address are re-rendered;
submitted invoices keep the text they were issued with.

Data only. Idempotent.
"""

import frappe
from frappe.contacts.doctype.address.address import get_address_display

TEMPLATE_NAME = "Saudi Arabia"

TEMPLATE = """{% if custom_building_number %}Building No. {{ custom_building_number }}, {% endif -%}{{ address_line1 }}<br>
{% if address_line2 and address_line2 != custom_area %}{{ address_line2 }}<br>{% endif -%}
{% if custom_area %}{{ custom_area }}<br>{% endif -%}
{% if city %}{{ city }}{% if pincode %} {{ pincode }}{% endif %}<br>{% elif pincode %}{{ pincode }}<br>{% endif -%}
{% if state and state != city %}{{ state }}<br>{% endif -%}
{% if country %}{{ country }}<br>{% endif -%}
{% if phone %}Phone: {{ phone }}<br>{% endif -%}
{% if fax %}Fax: {{ fax }}<br>{% endif -%}
{% if email_id %}Email: {{ email_id }}<br>{% endif -%}
"""


def execute():
	if not frappe.db.exists("Address Template", TEMPLATE_NAME):
		return
	current = frappe.db.get_value("Address Template", TEMPLATE_NAME, "template") or ""
	if "custom_building_number" in current:
		return
	frappe.db.set_value("Address Template", TEMPLATE_NAME, "template", TEMPLATE)
	frappe.clear_cache()
	rerender()


def _saudi_addresses():
	return set(frappe.get_all("Address", filters={"country": TEMPLATE_NAME}, pluck="name"))


def rerender():
	saudi = _saudi_addresses()
	if not saudi:
		return
	for si in frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 0},
		fields=["name", "customer_address", "company_address"],
	):
		updates = {}
		if si.customer_address in saudi:
			updates["address_display"] = get_address_display(si.customer_address)
		if si.company_address in saudi:
			updates["company_address_display"] = get_address_display(si.company_address)
		if updates:
			frappe.db.set_value("Sales Invoice", si.name, updates, update_modified=False)
	for c in frappe.get_all(
		"Customer",
		filters={"customer_primary_address": ["is", "set"]},
		fields=["name", "customer_primary_address"],
	):
		if c.customer_primary_address in saudi:
			frappe.db.set_value(
				"Customer",
				c.name,
				"primary_address",
				get_address_display(c.customer_primary_address),
				update_modified=False,
			)
