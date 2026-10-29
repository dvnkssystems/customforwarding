# Copyright (c) 2026, DVNKS Systems and contributors
"""Bills default to a buying-only price list, and stop adding Item Prices
(A-08 retest, 29 Oct).

The old server was set by hand on 27 Oct; the client's data came with the
buying price list "Selling Empty" and Auto insert Item Price on, so a bill
saved its rates as Item Prices on "Selling Empty" -- which a Server Script
then deletes. Same settings as the old server: Standard Buying, auto insert
off. Skipped when Standard Buying is missing.
"""

import frappe


def execute():
	if frappe.db.exists("Price List", {"name": "Standard Buying", "buying": 1, "enabled": 1}):
		frappe.db.set_single_value("Buying Settings", "buying_price_list", "Standard Buying")
		# What a new bill reads; Buying Settings sets it only when saved from its form.
		frappe.db.set_default("buying_price_list", "Standard Buying")
	frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 0)
