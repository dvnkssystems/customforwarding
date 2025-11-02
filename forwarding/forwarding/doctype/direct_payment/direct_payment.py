# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, add_days, nowdate, getdate, get_link_to_form
from frappe.model.document import Document

class DirectPayment(Document):
	def on_submit(self):
		jv_doc = frappe.new_doc("Journal Entry")
		jv_doc.posting_date = self.date
		# jv_doc.naming_series = "JV-{direct_payment_id}"
		jv_doc.voucher_type = self.voucher_type		
		jv_doc.user_remark = self.name
		jv_doc.cheque_date = self.cheque_date
		jv_doc.direct_payment_id = self.name
		jv_doc.cheque_no = self.cheque_no
		for row in self.shipping_payment_request_details:
			jv_doc.append("accounts", {
			"account": row.account,
			"project":row.project,
			"debit_in_account_currency": row.amount,
			"cost_center":row.cost_center
			})
		for row in self.account:
			jv_doc.append("accounts", {
			"account": row.account,
			"party_type":row.party_type,
			"cost_center":self.cost_center,
			"party":row.party,
			"project":row.project,
			"credit_in_account_currency": row.credit_amount,
			"debit_in_account_currency": row.debit_amount
			})				
		jv_doc.save()
		jv_doc.submit()
		self.reference_id = jv_doc.name
		frappe.db.commit()
