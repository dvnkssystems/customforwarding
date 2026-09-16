# Copyright (c) 2026, DVNKS Systems and contributors
"""Zero-rate VAT for overseas customers.

A Tax Rule sends every Sales Invoice for a customer in the OVERSEAS group to the
company's zero-rated VAT template instead of the default 15%. Item-level VAT
templates do not override it: they only adjust rates on accounts the invoice's
tax table carries, and the zero-rated template carries only the VAT Zero account.
"""

import frappe

CUSTOMER_GROUP = "OVERSEAS"


def execute():
	if not frappe.db.exists("Customer Group", CUSTOMER_GROUP):
		return

	for company in frappe.get_all("Company", pluck="name"):
		template = frappe.db.get_value(
			"Sales Taxes and Charges Template",
			{"company": company, "disabled": 0, "title": ["like", "%VAT Zero%"]},
			"name",
		)
		if not template:
			continue

		if frappe.db.exists(
			"Tax Rule",
			{"tax_type": "Sales", "customer_group": CUSTOMER_GROUP, "company": company},
		):
			continue

		frappe.get_doc(
			{
				"doctype": "Tax Rule",
				"tax_type": "Sales",
				"customer_group": CUSTOMER_GROUP,
				"company": company,
				"sales_tax_template": template,
				"priority": 1,
			}
		).insert(ignore_permissions=True)
