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
from forwarding.naming import service_name


# Before the declaration is filed there is no Bayan yet.
BAYAN_OPTIONAL_STATUS = "Draft"


class CustomClearance(Document):
	def autoname(self):
		"""C + the job number without hyphens (CRIA2607014), a letter added
		for a second one on the same job (M-13). With no job the DocType's own
		format names it, as before."""
		if self.operations:
			self.name = service_name("Custom Clearance", "C", self.operations)

	def after_insert(self):
		# Only the job's documents for the customs stage belong to the clearance.
		copy_from_job(self, "document_table", is_customs_document)
		# Container clearance and clearance documents moved here from the job
		# (D5); a job that still carries rows hands them over once.
		copy_from_job(self, "clearance_documents")

	def validate(self):
		self.validate_bayan()
		# The job keeps a copy of every cost row (forwarding.child_tables).
		sync_costs_to_job(self)
		self.add_job_containers()

	def validate_bayan(self):
		"""The Bayan is issued once the declaration is filed: Bayan No. and
		Bayan Date are required from Clearance Status Submitted on (the
		form's mandatory_depends_on), not on a Draft clearance (M-11)."""
		if (self.clearance_status or BAYAN_OPTIONAL_STATUS) == BAYAN_OPTIONAL_STATUS:
			return
		missing = [
			_(self.meta.get_label(fieldname))
			for fieldname in ("bayyan_number", "bayyan_date")
			if not self.get(fieldname)
		]
		if missing:
			frappe.throw(
				_("Enter {0}: the Bayan is required once Clearance Status is {1}.").format(
					", ".join(missing),
					frappe.bold(_(self.clearance_status)),
				),
				frappe.MandatoryError,
				title=_("Bayan details missing"),
			)

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