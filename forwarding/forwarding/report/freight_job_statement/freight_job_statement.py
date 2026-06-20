# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Job"), "fieldname": "job", "fieldtype": "Link", "options": "Operations", "width": 200},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": _("Mode"), "fieldname": "mode_of_shipment", "fieldtype": "Data", "width": 90},
		{"label": _("AWB/BL"), "fieldname": "awb_number", "fieldtype": "Data", "width": 130},
		{"label": _("Income"), "fieldname": "income", "fieldtype": "Currency", "width": 120},
		{"label": _("Cost"), "fieldname": "cost", "fieldtype": "Currency", "width": 120},
		{"label": _("Balance"), "fieldname": "balance", "fieldtype": "Currency", "width": 120},
		{"label": _("Billing Status"), "fieldname": "billing_status", "fieldtype": "Data", "width": 130},
	]


def get_data(filters):
	conds = {}
	if filters.get("customer"):
		conds["customer"] = filters["customer"]
	if filters.get("branch"):
		conds["branch"] = filters["branch"]
	if filters.get("from_date") and filters.get("to_date"):
		conds["date"] = ["between", [filters["from_date"], filters["to_date"]]]

	jobs = frappe.get_all(
		"Operations", filters=conds,
		fields=["name", "customer", "date", "mode_of_shipment", "awb_number", "billing_status"],
		order_by="date desc",
	)
	data = []
	for j in jobs:
		rows = frappe.get_all(
			"Cost Table", filters={"parent": j.name, "parenttype": "Operations"},
			fields=["rate", "cost", "received_amount", "paid_amount"],
		)
		income = sum(flt(r.received_amount) or flt(r.rate) for r in rows)
		cost = sum(flt(r.paid_amount) or flt(r.cost) for r in rows)
		data.append({
			"job": j.name, "customer": j.customer, "date": j.date,
			"mode_of_shipment": j.mode_of_shipment, "awb_number": j.awb_number,
			"income": income, "cost": cost, "balance": income - cost,
			"billing_status": j.billing_status,
		})
	return data
