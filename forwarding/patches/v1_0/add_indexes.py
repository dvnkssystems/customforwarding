# Copyright (c) 2026, DVNKS Systems and contributors
"""Add DB indexes on hot Operations columns for report/list performance."""

import frappe


def execute():
	indexes = {
		"Operations": ["customer", "billing_status", "date", "operations_status"],
		"Sales Invoice": ["operations"],
		"Purchase Invoice": ["operations"],
		"Freight Voucher": ["freight_job"],
		"Freight Job Status": ["freight_job"],
	}
	for doctype, columns in indexes.items():
		if not frappe.db.table_exists(doctype):
			continue
		for col in columns:
			try:
				if frappe.db.has_column(doctype, col):
					frappe.db.add_index(doctype, [col])
			except Exception:
				frappe.log_error(f"forwarding add_index failed: {doctype}.{col}")
