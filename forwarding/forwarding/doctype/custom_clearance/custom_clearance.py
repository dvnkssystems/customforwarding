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
from forwarding.clearance_documents import mark_customs_rows, sync_to_job
from forwarding.naming import service_name


# Before the declaration is filed there is no Bayan yet; a clearance can also
# be rejected before it was filed (R3-39: Rejected from any step).
BAYAN_OPTIONAL_STATUS = "Draft"
BAYAN_OPTIONAL_STATUSES = (BAYAN_OPTIONAL_STATUS, "Rejected")


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
		# (D5); a job that still carries rows hands them over once. That
		# Clearance Documents table is hidden now (R3-36): documents live in
		# the Documents table, shared with the job.
		copy_from_job(self, "clearance_documents")

	def validate(self):
		# Its Documents table is the job's Customs Clearance rows (R3-36).
		mark_customs_rows(self)
		self.validate_bayan_number()
		self.validate_bayan()
		# The job keeps a copy of every cost row (forwarding.child_tables).
		sync_costs_to_job(self)
		self.add_job_containers()

	def validate_bayan_number(self):
		"""Bayan No. is digits only (R3-41); no length rule yet. Spaces are
		dropped. Checked when the number is entered or changed, so an old
		record with a placeholder still saves until someone edits it."""
		number = "".join((self.bayyan_number or "").split())
		self.bayyan_number = number or None
		if not number or number.isdigit() and number.isascii():
			return
		before = self.get_doc_before_save() if not self.is_new() else None
		if before and "".join((before.bayyan_number or "").split()) == number:
			return
		frappe.throw(
			_("{0} must contain digits only.").format(_(self.meta.get_label("bayyan_number"))),
			title=_("Invalid Bayan No."),
		)

	def validate_bayan(self):
		"""The Bayan is issued once the declaration is filed: Bayan No. and
		Bayan Date are required from Clearance Status Submitted to Customs on (the
		form's mandatory_depends_on), not on a Draft clearance (M-11)."""
		if (self.clearance_status or BAYAN_OPTIONAL_STATUS) in BAYAN_OPTIONAL_STATUSES:
			return
		missing = [
			_(self.meta.get_label(fieldname))
			for fieldname in ("bayyan_number", "bayyan_date")
			if not self.get(fieldname)
		]
		if missing:
			# Frappe's own mandatory wording, so the app can point at each field.
			frappe.throw(
				"<br>".join(_("Value missing for {0}: {1}").format(_(self.doctype), label) for label in missing),
				frappe.MandatoryError,
				title=_("Bayan required once Clearance Status is {0}").format(_(self.clearance_status)),
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
		sync_to_job(self)
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