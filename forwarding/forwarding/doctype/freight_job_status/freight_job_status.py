# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FreightJobStatus(Document):
	def add_status(self, status_text, status_date=None):
		self.status_text = status_text
		self.status_date = status_date or frappe.utils.now_datetime()
		self.append("status_history", {
			"status_text": status_text,
			"status_date": self.status_date,
			"updated_by": frappe.session.user,
		})
		self.save()
