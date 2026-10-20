# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.jinja import validate_template


class JobBannerRule(Document):
	def validate(self):
		from forwarding.banners import CONDITIONS

		if self.condition_key not in CONDITIONS:
			frappe.throw(
				_("Condition {0} is not defined in forwarding.banners").format(
					frappe.bold(self.condition_key)
				)
			)
		if self.message_template:
			validate_template(self.message_template)

	def on_update(self):
		# Every cached Job 360 payload carries rendered banners.
		frappe.cache.delete_keys("job_360:")

	def on_trash(self):
		frappe.cache.delete_keys("job_360:")
