# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FreightWaybill(Document):
	def before_save(self):
		if self.terms_and_conditions and not self.terms_text:
			self.terms_text = frappe.db.get_value("Waybill Terms", self.terms_and_conditions, "terms_content")

	@frappe.whitelist()
	def approve(self):
		self.is_approved = 1
		self.approved_by = frappe.session.user
		self.save()
		return True

	@frappe.whitelist()
	def generate_public_link(self):
		import uuid
		if not self.public_token:
			self.public_token = uuid.uuid4().hex
		self.is_public = 1
		self.save()
		return self.public_token
