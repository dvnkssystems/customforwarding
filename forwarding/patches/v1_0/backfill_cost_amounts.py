# Copyright (c) 2026, DVNKS Systems and contributors
"""Cost Table.amount is the row's buying amount, Cost alone (spec Q3)."""

import frappe


def execute():
	frappe.reload_doc("forwarding", "doctype", "cost_table")
	table = frappe.qb.DocType("Cost Table")
	frappe.qb.update(table).set(table.amount, table.cost).run()
