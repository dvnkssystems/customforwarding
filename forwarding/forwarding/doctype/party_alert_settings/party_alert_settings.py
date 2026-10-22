# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Thresholds behind the Customer 360 / Supplier 360 banners and the supplier
Cost variance tile. Provisional (Phase 2 spec §6.1, §6.2): kept as settings so
they can change after the freight process review without code."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

DEFAULTS = {
	"cost_variance_threshold": 5.0,
	"rate_expiry_days": 7,
	"document_expiry_days": 30,
	"quote_expiry_days": 3,
}


class PartyAlertSettings(Document):
	def validate(self):
		for field in ("rate_expiry_days", "document_expiry_days", "quote_expiry_days"):
			if cint(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative").format(self.meta.get_label(field)))
		if flt(self.cost_variance_threshold) < 0:
			frappe.throw(_("Cost Variance Threshold cannot be negative"))

	def on_update(self):
		# Cached Customer / Supplier 360 payloads carry KPIs and banners worked
		# out with the old values.
		from forwarding.job_events import CUSTOMER_CACHE_PREFIX, SUPPLIER_CACHE_PREFIX

		for prefix in (CUSTOMER_CACHE_PREFIX, SUPPLIER_CACHE_PREFIX):
			frappe.cache.delete_keys(prefix)


def get_settings():
	"""The thresholds, each falling back to its default while the Single has
	never been saved (or a value was cleared)."""
	out = frappe._dict(DEFAULTS)
	# Uncast, so an empty value reads as empty rather than 0.
	saved = frappe.db.get_singles_dict("Party Alert Settings", cast=False)
	for field, default in DEFAULTS.items():
		value = saved.get(field)
		if value is None or value == "":
			continue
		out[field] = flt(value) if isinstance(default, float) else cint(value)
	return out
