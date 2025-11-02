# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class ContainerBookingRequest(Document):
	pass
		# def on_update(self):
		# fields_to_transfer = ['awb_number']
		# if self.operations:
		# 	for field in fields_to_transfer:
		# 		local_field_value = self.get(field)
		# 		frappe.db.set_value("Operations",self.operations,field,local_field_value)
		# 		# frappe.msgprint(_("Updated {0} in Operations {1}".format(field,self.operations)))
