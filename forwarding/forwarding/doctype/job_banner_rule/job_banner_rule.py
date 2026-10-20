# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.jinja import validate_template

MODULES = {
	"Operations": "forwarding/banners.py",
	"Customer": "forwarding/customer_banners.py",
	"Supplier": "forwarding/supplier_banners.py",
}


class JobBannerRule(Document):
	def validate(self):
		from forwarding.banners import conditions_for

		self.applies_to = self.applies_to or "Operations"
		if self.condition_key not in conditions_for(self.applies_to):
			frappe.throw(
				_("Condition {0} is not defined for {1} in {2}").format(
					frappe.bold(self.condition_key),
					frappe.bold(self.applies_to),
					MODULES.get(self.applies_to, MODULES["Operations"]),
				)
			)
		if self.applies_to != "Operations":
			# The worklist counts jobs; a Customer or Supplier rule has none.
			self.show_on_worklist = 0
		if self.message_template:
			validate_template(self.message_template)

	def on_update(self):
		# Every cached Job / Customer / Supplier 360 payload and the worklist
		# carry rendered banners.
		_clear_caches()

	def on_trash(self):
		_clear_caches()


def _clear_caches():
	from forwarding.job_events import (
		CACHE_PREFIX,
		CUSTOMER_CACHE_PREFIX,
		SUPPLIER_CACHE_PREFIX,
		bump_worklist_version,
	)

	for prefix in (CACHE_PREFIX, CUSTOMER_CACHE_PREFIX, SUPPLIER_CACHE_PREFIX):
		frappe.cache.delete_keys(prefix)
	bump_worklist_version()
