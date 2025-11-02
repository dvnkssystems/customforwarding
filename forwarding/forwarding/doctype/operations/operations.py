# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cstr, flt, getdate, cint, nowdate, add_days, get_link_to_form, strip_html
from frappe.contacts.doctype.address.address import get_company_address
from erpnext.stock.doctype.item.item import get_item_defaults
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults


class Operations(Document):
	def on_update(self):
		fields_to_transfer = ['awb_number']
		fields_to_transfer_project = ['cost_center']
		if self.freight:
			for field in fields_to_transfer:
				local_field_value = self.get(field)
				frappe.db.set_value("Freight",self.freight,field,local_field_value)
				# frappe.db.sql("""UPDATE `tabFreight` SET %s=%s where name=%s""",(field,local_field_value,self.freight))
				# frappe.msgprint(_("Updated {0} in Frieght {1}".format(field,self.freight)))
		if self.custom_clearance_id:
			for field in fields_to_transfer:
				local_field_value = self.get(field)
				frappe.db.set_value("Custom Clearance",self.custom_clearance,field,local_field_value)
				# frappe.msgprint(_("Updated {0} in Frieght {1}".format(field,self.custom_clearance)))
		if self.project:
			for field in fields_to_transfer_project:
				local_field_value = self.get(field)
				frappe.db.set_value("Project",self.project,field,local_field_value)
				# frappe.msgprint(_("Updated {0} in Project {1}".format(field,self.project)))
		# else:
		# 	if(frappe.db.exists("Project",self.name)):
		# 		self.set('project',self.name)
		# 	else:
		# 		project = frappe.get_doc({
		# 					"doctype":"Project",
		# 					"name":self.name,
		# 					"operations":self.name,
		# 					"cost_center":self.cost_center,
		# 					"customer":self.customer
		# 				})
		# 		try:
		# 			project.insert()
		# 			self.set('project',project.name)
		# 		except Exception as e:
		# 			frappe.log_error(message=e,title="Error creating project in operations")
				


# def _create_project(pr):
#     c = frappe.new_doc("Project")
#     c.project_name = pr.name
#     c.insert()
#     frappe.db.commit()
#     d = frappe.utils.get_link_to_form('Project', c.name)
#     frappe.msgprint(_("Projject {0} Created").format(d))
#     return c.name


# def create_project(doc,method):
#     pr = frappe.get_doc("Operations",doc.name)
#     if frappe.db.exists("Project", pr.name):
#         d = frappe.get_doc("Project",pr.name)
#         frappe.set_value("Project",pr.name,"name",d.name)
#         i.reload()
#         frappe.throw(_("Project {0} already exists").format(d))
#     else:
#         cd = _create_project_(pr)
#         frappe.db.set_value("Project", pr.name, "name", cd)
#         i.reload()
#         frappe.db.commit()
#         pr.reload()
@frappe.whitelist()
def make_freight(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
	
	def set_missing_values(source, target):
		pass

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Freight",
			"field_map": {

			}
		}
	}, target_doc, postprocess, ignore_permissions= ignore_permissions)

	return doclist

@frappe.whitelist()
def make_custom_clearance(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
	
	def set_missing_values(source, target):
		pass
		
	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Custom Clearance",
			"field_map": {

			}
		}
	}, target_doc, postprocess, ignore_permissions= ignore_permissions)

	return doclist

@frappe.whitelist()
def make_transportaion(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
	
	def set_missing_values(source, target):
		pass
		
	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Transportation",
			"field_map": {

			}
		}
	}, target_doc, postprocess, ignore_permissions= ignore_permissions)

	return doclist
	
@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
		#Get the advance paid Journal Entries in Sales Invoice Advance
		if target.get("allocate_advances_automatically"):
			target.set_advances()

	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = True
		target.run_method("set_missing_values")
		target.run_method("set_po_nos")
		target.run_method("calculate_taxes_and_totals")

		if source.company_address:
			target.update({'company_address': source.company_address})
		else:
			# set company address
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Sales Invoice", 'company_address', target.company_address))

		# set the redeem loyalty points if provided via shopping cart
		# if source.loyalty_points and source.order_type == "Shopping Cart":
		# 	target.redeem_loyalty_points = 1

	def update_item(source, target, source_parent):
		target.amount = flt(source.rate)
		# target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = 1

		if source_parent.project:
			target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")
		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") \
				or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Sales Invoice",
			"field_map": {
				"name":"operations",
				"party_account_currency": "party_account_currency",
				"payment_terms_template": "payment_terms_template"
			},
			# "validation": {
			# 	"docstatus": ["=", 1]
			# }
		},
		"Cost Table": {
			"doctype": "Sales Invoice Item",
			"field_map": {
				"item": "item_code",
				"name":"cost_table"
			},
			"postprocess": update_item,
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"add_if_empty": True
		}
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist

@frappe.whitelist()
def make_purchase_invoice(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
		#Get the advance paid Journal Entries in Purchase Invoice Advance
		if target.get("allocate_advances_automatically"):
			target.set_advances()

	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = True
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

		if source.company_address:
			target.update({'company_address': source.company_address})
		else:
			# set company address
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Purchase Invoice", 'company_address', target.company_address))

		# set the redeem loyalty points if provided via shopping cart
		# if source.loyalty_points and source.order_type == "Shopping Cart":
		# 	target.redeem_loyalty_points = 1

	def update_item(source, target, source_parent):
		target.amount = flt(source.rate)
		# target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = 1

		if source_parent.project:
			target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")
		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") \
				or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Purchase Invoice",
			"field_map": {
				"name":"operations",
				"party_account_currency": "party_account_currency",
				"payment_terms_template": "payment_terms_template"
			},
			# "validation": {
			# 	"docstatus": ["=", 1]
			# }
		},
		"Cost Table": {
			"doctype": "Purchase Invoice Item",
			"field_map": {
				"item": "item_code",
				"name":"cost_table",
				"cost":"rate"
			},
			"postprocess": update_item,
		},
		"Purchase Taxes and Charges": {
			"doctype": "Purchase Taxes and Charges",
			"add_if_empty": True
		}
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist


@frappe.whitelist()
def make_booking(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
		# #Get the advance paid Journal Entries in Purchase Invoice Advance
		# if target.get("allocate_advances_automatically"):
		# 	target.set_advances()

	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = True
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

		# if source.company_address:
		# 	target.update({'company_address': source.company_address})
		# else:
		# 	# set company address
		# 	target.update(get_company_address(target.company))

		# if target.company_address:
		# 	target.update(get_fetch_values("Purchase Invoice", 'company_address', target.company_address))

		# set the redeem loyalty points if provided via shopping cart
		# if source.loyalty_points and source.order_type == "Shopping Cart":
		# 	target.redeem_loyalty_points = 1

	def update_item(source, target, source_parent):
		# target.amount = flt(source.rate)
		# # target.base_amount = target.amount * flt(source_parent.conversion_rate)
		# target.qty = 1

		if source_parent.project:
			target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")
		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Container Booking Request",
			"field_map": {
				# "name":"operations",
				# "party_account_currency": "party_account_currency",
				# "payment_terms_template": "payment_terms_template"
			}
			# "validation": {
			# 	"docstatus": ["=", 1]
			# }
		}
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist

	@frappe.whitelist()
	def make_delivery_note(source_name, target_doc=None, skip_item_mapping=False):
		def set_missing_values(source, target):
			target.ignore_pricing_rule = 1
			target.run_method("set_missing_values")
			target.run_method("set_po_nos")
			# target.run_method("calculate_taxes_and_totals")

			# if source.company_address:
			# 	target.update({'company_address': source.company_address})
			# else:
			# 	# set company address
			# 	target.update(get_company_address(target.company))

			# if target.company_address:
			# 	target.update(get_fetch_values("Delivery Note", 'company_address', target.company_address))

		def update_item(source, target, source_parent):
			# target.base_amount = (flt(source.qty)) * flt(source.base_rate)
			# target.amount = (flt(source.qty)) * flt(source.rate)
			target.qty = flt(source.qty) 
			target.pr_discount = flt(source.pr_discount) 
			target.po_rate = flt(source.rate) 

			item = get_item_defaults(target.item_code, source_parent.company)
			# item_group = get_item_group_defaults(target.item_code, source_parent.company)

			# if item:
			# 	target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center") \
			# 		or item.get("buying_cost_center") \
			# 		or item_group.get("buying_cost_center")

		mapper = {
			"Purchase Receipt": {
				"doctype": "Delivery Note",
				"validation": {
					"docstatus": ["=", 1]
				}
			}
		}

		if not skip_item_mapping:
			mapper["Purchase Receipt Item"] = {
				"doctype": "Delivery Note Item",
				"field_map": {
					"qty":"qty",
					"parent": "purchase_receipt_item",
				},
				"postprocess": update_item,
				# "condition": lambda doc: abs(doc.qty) < abs(doc.qty) and doc.delivered_by_supplier!=1
			}

		target_doc = get_mapped_doc("Purchase Receipt", source_name, mapper, target_doc, set_missing_values)

		return target_doc