# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document

from forwarding.child_tables import (
	add_clearance_containers,
	copy_from_job,
	is_customs_document,
	job_containers,
	sync_costs_to_job,
)


class CustomClearance(Document):
	def after_insert(self):
		# Only the job's documents for the customs stage belong to the clearance.
		copy_from_job(self, "document_table", is_customs_document)
		# Container clearance and clearance documents moved here from the job
		# (D5); a job that still carries rows hands them over once.
		copy_from_job(self, "clearance_documents")

	def validate(self):
		# The job keeps a copy of every cost row (forwarding.child_tables).
		sync_costs_to_job(self)
		self.add_job_containers()

	def add_job_containers(self):
		"""List every container of the job, Pending until cleared. A job's
		old clearance rows come first, so their statuses carry over."""
		if not self.operations:
			return
		job = frappe.get_doc("Operations", self.operations)
		if self.is_new() and not self.get("clearance_containers"):
			for row in job.get("clearance_containers") or []:
				self.append("clearance_containers", row.as_dict(no_default_fields=True))
		add_clearance_containers(self, job_containers(job))

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
			fields = ["sequence_id", "activity", "status", "remark", "is_finish_activity","date"]

			for row in frappe.get_all("Activity Template Table", fields = fields,
				filters = {'parenttype': 'Activity Template', 'parent': self.activity_template}, order_by="sequence_id, idx"):
				child = self.append('activity_template_table', row)