# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FreightJobRequest(Document):
	@frappe.whitelist()
	def create_job(self):
		if self.linked_job:
			frappe.throw(frappe._("Already linked to {0}").format(self.linked_job))
		job = frappe.new_doc("Operations")
		job.awb_number = self.awb_bl_no
		job.cargo_description = self.cargo_description
		job.flags.ignore_mandatory = True
		job.insert(ignore_permissions=True)
		self.db_set("linked_job", job.name)
		self.db_set("status", "Linked")
		return job.name
