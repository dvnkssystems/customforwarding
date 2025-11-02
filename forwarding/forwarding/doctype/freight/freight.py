# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document

class Freight(Document):
	def update_cost_table_in_operations(self):
		pass

	def validate(self):
		"""update operation cost table 
			update refid in cost table

		"""
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
							"cost":row.cost
					
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
				local_field_value = self.get(field)
				frappe.db.set_value("Operations",self.operations,field,local_field_value)
				frappe.msgprint(_("Updated {0} in Operations {1}".format(field,self.operations)))
				
	def get_template(self):
		if self.activity_template:
			self.set("activity_template_table", [])
			fields = ["sequence_id", "activity", "status", "remark", "is_finish_activity"]

			for row in frappe.get_all("Activity Template Table", fields = fields,
				filters = {'parenttype': 'Activity Template', 'parent': self.activity_template}, order_by="sequence_id, idx"):
				child = self.append('activity_template_table', row)			
	
@frappe.whitelist()
def delete_cost_table_doc(operations):
	doc = frappe.get_doc("Cost Table",name)
	try:
		doc.delete()
		frappe.db.commit()
		frappe.msgprint(_("Deleted linked Cost table Entry {0} from {1}".format(doc.name,doc.parent)))
	except:
		frappe.db.rollback()
		traceback = frappe.get_traceback()
		frappe.log_error(message=traceback)
