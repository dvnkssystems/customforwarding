# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, erpnext
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate, getdate, nowdate

from forwarding.child_tables import copy_from_job, sync_costs_to_job
from forwarding.naming import service_name


class Transportation(Document):
	def autoname(self):
		"""T + the job number without hyphens (TRIA2607014), a letter added
		for a second one on the same job (M-13). With no job the DocType's own
		format names it, as before."""
		if self.operations:
			self.name = service_name("Transportation", "T", self.operations)

	def after_insert(self):
		# The job's containers and documents travel with the transport leg.
		copy_from_job(self, "container_details")
		copy_from_job(self, "document_table")

	def warn_expired_papers(self):
		"""Warn, without blocking, when the vehicle's insurance or the driver's
		licence has run out. ERPNext's Vehicle has no registration expiry field,
		so insurance (end_date) is the only vehicle date checked."""
		today = getdate(nowdate())
		lines = []
		if self.vehicle:
			end = frappe.db.get_value("Vehicle", self.vehicle, "end_date")
			if end and getdate(end) < today:
				lines.append(_("Insurance of vehicle {0} expired on {1}").format(
					frappe.bold(self.vehicle), formatdate(end)))
		if self.driver:
			expiry = frappe.db.get_value("Driver", self.driver, "expiry_date")
			if expiry and getdate(expiry) < today:
				lines.append(_("Licence of driver {0} expired on {1}").format(
					frappe.bold(self.driver), formatdate(expiry)))
		if lines:
			frappe.msgprint("<br>".join(lines), title=_("Expired papers"), indicator="orange")
		return lines

	def validate(self):
		self.warn_expired_papers()
		# The job keeps a copy of every cost row (forwarding.child_tables).
		sync_costs_to_job(self)

	def on_update(self):
		fields_to_transfer = ['awb_number']
		if self.operations:
			for field in fields_to_transfer:
				# Neither this DocType nor its customisations carry these fields
				# today; copying a missing one wrote NULL over the job's value.
				if not self.meta.has_field(field) or not self.get(field):
					continue
				local_field_value = self.get(field)
				frappe.db.set_value("Operations",self.operations,field,local_field_value)
				frappe.msgprint(_("Updated {0} in Operations {1}").format(field, self.operations))

	def get_template(self):
		if self.activity_template:
			self.set("activity_template_table", [])
			fields = ["sequence_id", "activity", "status", "remark", "is_finish_activity"]

			for row in frappe.get_all("Activity Template Table", fields = fields,
				filters = {'parenttype': 'Activity Template', 'parent': self.activity_template}, order_by="sequence_id, idx"):
				child = self.append('activity_template_table', row)