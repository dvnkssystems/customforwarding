# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, erpnext
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate, getdate, nowdate

from forwarding.child_tables import copy_from_job


class Transportation(Document):
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
		"""update operation cost table 
			update refid in cost table

		"""
		self.warn_expired_papers()
		if self.cost_table:
			for row in self.cost_table:
				if row.ref_id:
					self.update_cost_table_in_operations()
				else:
					print("in else")
					ref_name = frappe.get_all("Cost Table",filters={"parent":self.operations,"item":row.item},fields=['name'])
					print(ref_name)
					if ref_name:
						row.ref_id = ref_name[0].name
					else:
						cost_table_doc = frappe.get_doc({
							"doctype":"Cost Table",
							'parent': self.operations,
							'parentfield': 'cost_table',
							'parenttype': 'Operations',
							"item":row.item,
							"account":row.account,
							"cost":row.cost,
							"amount":row.cost,
						})
						try:
							cost_table_doc.insert()
							# row.ref_id = 
							frappe.db.set_value(row.doctype,row.name,"ref_id",cost_table_doc.name)
						except:
							frappe.db.rollback()
							traceback = frappe.get_traceback()
							frappe.log_error(message=traceback)
							frappe.msgprint("Error adding cost table in operations")
						
			# self.save()
			frappe.db.commit()

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