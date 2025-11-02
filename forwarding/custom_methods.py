import frappe 
from frappe.model.mapper import get_mapped_doc

@frappe.whitelist()
def get_cost_table_details(project):
	items = []
	items = frappe.get_all("Cost Table",filters={"parent":project},fields=["item"])
	return [item['item'] for item in items]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters):
	items = []
	project = filters.get("project")
	items = frappe.get_all("Cost Table",filters={"parent":project},fields=["item","item_name"])
	# return [item['item'] for item in items]
	return frappe.db.sql(""" select item, item_name  from `tabCost Table` 
			where parent=%(parent)s and docstatus < 2 and item like %(txt)s
			order by item limit {start}, {page_len}""".format(parent=filters.get('project'), start = start,page_len = page_len),{'parent': filters.get('project'), 'txt': "%%%s%%" % txt})

@frappe.whitelist()
def get_cost_table_details(project, item):
	return frappe.db.get_all("Cost Table",filters={"parent":project,"item":item},
									fields=["name","pending_amount"])
									
def update_cost_table_in_operations(doc,method=None):
	frappe.msgprint(doc.name)
	items = doc.get("items")
	if doc.docstatus != 2 and doc.operations and doc.update_cost:
		for item in items:
			frappe.msgprint(item.cost_table)
			cost_table_doc = frappe.get_cached_doc("Cost Table",item.cost_table)
			if doc.doctype=="Sales Invoice":
				cost_table_doc.received_amount += item.amount
			if doc.doctype=="Purchase Invoice":
				cost_table_doc.paid_amount += item.amount
			cost_table_doc.save()
			frappe.db.commit()
			
def update_cost_table_in_operations_on_cancle(doc,method=None):
	items = doc.get("items")
	if doc.status == "Paid" and doc.operations  and doc.update_cost:
		for item in items:
			cost_table_doc = frappe.get_cached_doc("Cost Table",item.cost_table)
			if doc.doctype=="Sales Invoice":
				cost_table_doc.received_amount -= item.amount
			if doc.doctype=="Purchase Invoice":
				cost_table_doc.paid_amount -= item.amount
			cost_table_doc.save()
			frappe.db.commit()


@frappe.whitelist()
def make_operations(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)

	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = True
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(obj, target, source_parent):
		target.rate = flt(obj.rate) * flt(obj.qty)

	doclist = get_mapped_doc("Quotation", source_name, {
		"Quotation": {
			"doctype": "Operations",
			"field_map": {
				"name":"from_quotation",
				 "from_location": "port_of_loading",
				 "to_location": "port_of_destination",
				 "party_name": "customer"
			},
		"Quotation Item": {
			"doctype": "Cost Table",
			"field_map": {
				"item_code": "item",
				"parent": "prevdoc_docname"
			},
			"postprocess": update_item,

			# "validation": {
			# 	"docstatus": ["=", 1]
			# }
			}
		} 
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist