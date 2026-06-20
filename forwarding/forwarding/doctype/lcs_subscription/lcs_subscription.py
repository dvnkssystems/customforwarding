# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LCSSubscription(Document):
	PLAN_LIMITS = {
		"Bridge Lite": {"max_contacts": 100, "max_jobs": 250, "max_invoices": 300, "max_vouchers": 750, "max_awb_tracking": 50},
		"Bridge Growth": {"max_contacts": 500, "max_jobs": 1000, "max_invoices": 2000, "max_vouchers": 5000, "max_awb_tracking": 250},
		"Enterprise": {"max_contacts": 2000, "max_jobs": 5000, "max_invoices": 10000, "max_vouchers": 20000, "max_awb_tracking": 1000},
		"Enterprise Plus": {"max_contacts": 0, "max_jobs": 0, "max_invoices": 0, "max_vouchers": 0, "max_awb_tracking": 0},
	}

	def validate(self):
		# Auto-fill limits from the plan if not manually set (0 = unlimited)
		limits = self.PLAN_LIMITS.get(self.plan)
		if limits:
			for k, v in limits.items():
				if not self.get(k):
					self.set(k, v)
		self.refresh_usage()

	def refresh_usage(self):
		self.used_jobs = frappe.db.count("Operations")
		self.used_invoices = frappe.db.count("Sales Invoice", {"docstatus": ["<", 2]})
		self.used_vouchers = frappe.db.count("Freight Voucher", {"docstatus": ["<", 2]})
		self.used_awb_tracking = frappe.db.count("Freight Tracking")
		self.used_contacts = frappe.db.count("Customer") + frappe.db.count("Supplier")
