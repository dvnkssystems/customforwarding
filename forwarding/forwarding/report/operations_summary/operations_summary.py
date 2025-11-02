# Copyright (c) 2013, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
import pandas as pd
from frappe.utils import flt

def execute(filters=None):
	columns, data = [], []
	columns = get_columns()
	row = {}
	items = get_data(filters)
	for item in items:
		cost_table_details_ = get_cost_table_details(item.operations)
		cost_table_details = [dict(ct_dict_) for ct_dict_ in cost_table_details_]
		df = pd.DataFrame(cost_table_details)
		if not df.empty:
			total = df.sum()
			item.update({	
							"item":'',
							"account":"Total",
							"cost":total['cost'],
							"rate":total['rate'],
							"paid_amount":total['paid_amount'],
							'pending_amount': total['pending_amount'],
							'received_amount': total['received_amount'],
							'pending_amount_to_receive': total['pending_amount_to_receive'],
							})
			pnl = flt(total['received_amount']) - flt(total['paid_amount'])
			item.update({'pnl':pnl})

		item.update({"indent":0})
		data.append(item)
		
		if cost_table_details:
			for ct in cost_table_details:
				row = {"indent":1}
				row.update(ct)
				row.update({"pnl":flt(flt(ct['received_amount']) - flt(ct['paid_amount']))})
				data.append(row)

	return columns, data

def get_conditions(filters):
	conditions = ""
	if filters.get('operations'):
		conditions += "and name = %(operations)s"# %filters.get('operations')

	if filters.get('job_type'):
		conditions += "and job_type = %(job_type)s"# %filters.get('operations')

	if filters.get('branch'):
		conditions += "and branch = %(branch)s"# %filters.get('operations')

	if filters.get('from_date'):
		conditions += "AND date >= %(from_date)s"# %filters.get('from_date')
	if filters.get('to_date'):
		conditions += "AND date <= %(to_date)s"# %filters.get('to_date')

	return conditions

def get_data(filters):
	conditions = get_conditions(filters)
	# from_date = filters.get("from_date")
	# to_date = filters.get("to_date")
	items =  frappe.db.sql(''' 
			select
				date,
				name as operations  ,
				mode_of_shipment ,
				branch ,
				cost_center ,
				scope_of_work ,
				job_type ,
				customer ,
				consignee
			from
				`tabOperations` 
			where
				docstatus != 2
					%s
			
		''' %conditions,filters,as_dict=1)
	
	return items

def get_cost_table_details(operations):
	return frappe.db.get_all("Cost Table",
							filters={"parent":operations},
							fields=['item','account','cost','rate','paid_amount',
									'pending_amount',
									'received_amount',
									'pending_amount_to_receive'
									])

def get_columns():
	columns = [
		{
			'label': _("Date"),
			'fieldname': 'date',
			'fieldtype': 'Date',
			'width': 120
		},
		{
			'label': _("Operations"),
			'fieldname': 'operations',
			'fieldtype': 'Link',
			'options': 'Operations',
			'width': 220
		},
		{
			'label': _("Mode of Shipment"),
			'fieldname': 'mode_of_shipment',
			'fieldtype': 'Data',
			'width': 80
		},
		{
			'label': _("Scope of Work"),
			'fieldname': 'scope_of_work',
			'fieldtype': 'Data',
			'width': 80
		},
		{
			'label': _("Branch"),
			'fieldname': 'branch',
			'fieldtype': 'Link',
			'options': 'Branch',
			'width': 80
		},
		{
			'label': _("Job Type"),
			'fieldname': 'job_type',
			'fieldtype': 'Data',
			'width': 80
		},
		{
			'label': _("Customer"),
			'fieldname': 'customer',
			'fieldtype': 'Link',
			"options":"Customer",
			'width': 80
		},
		{
			'label': _("Consignee"),
			'fieldname': 'consignee',
			'fieldtype': 'Link',
			"options":"Consignee",
			'width': 80
		},
		{
			'label': _("Item"),
			'fieldname': 'item',
			'fieldtype': 'Link',
			"options":"Item",
			'width': 80
		},
		{
			'label': _("Account"),
			'fieldname': 'account',
			'fieldtype': 'Link',
			"options":"Account",
			'width': 80
		},
		{
			'label': _("Estimated Income"),
			'fieldname': 'rate',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		},
		{
			'label': _("Estimated Cost"),
			'fieldname': 'cost',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		},
		{
			'label': _("Estimated Profit/Loss"),
			'fieldname': 'cost',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		},
		{
			'label': _("Actual Income" ),
			'fieldname': 'pending_amount_to_receive',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		},				
		{
			'label': _("Actual Cost"),
			'fieldname': 'pending_amount',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		},
		{
			'label': _("Paid Amount"),
			'fieldname': 'paid_amount',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		},
		{
			'label': _("Received Amount"),
			'fieldname': 'received_amount',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		},
		{
			'label': _("Actual Profit/Loss"),
			'fieldname': 'pnl',
			'fieldtype': 'Currency',
			"options":"Currency",
			'width': 80
		}
		]
	return columns