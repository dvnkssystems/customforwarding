# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from . import __version__ as app_version

app_name = "forwarding"
app_title = "Forwarding"
app_publisher = "FirstERP"
app_description = "forwarding"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "basant@criscocnsulting.in"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
#app_include_css = "/assets/forwarding/css/style.css"
# app_include_js = "/assets/forwarding/js/forwarding.js"

# include js, css files in header of web template
#web_include_css = "/assets/forwarding/css/style.css"
# web_include_js = "/assets/forwarding/js/forwarding.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "forwarding/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "forwarding.install.before_install"
# after_install = "forwarding.install.after_install"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "forwarding.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Jinja
# -----
# Used by the "Freight Tax Invoice" print format.
jinja = {
	"methods": ["forwarding.invoice_print.get_tax_invoice_context"],
}

# Fixtures
# --------
fixtures = [
	"Freight Activity Code",
	"Permit Type",
	{
		"dt": "Role",
		"filters": [["name", "in", [
			"Freight Admin", "Freight Manager", "Freight Operator",
			"Freight Finance", "Freight Sales", "Freight Viewer",
		]]],
	},
	# Quote is a custom DocType — it lives in the database, not on disk, so
	# without this its fields never reach another site.
	{
		"dt": "DocType",
		"filters": [["name", "in", ["Quote"]]],
	},
]

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		"validate": [
			"forwarding.subscription.enforce_limit",
			"forwarding.sales_invoice.enforce_overseas_zero_rating",
		],
		"before_submit": "forwarding.sales_invoice.block_zero_value_job_invoice",
		"on_update": [
			"forwarding.custom_methods.update_cost_table_in_operations",
			"forwarding.job_events.on_sales_invoice_change",
		],
		"on_submit": "forwarding.job_events.on_sales_invoice_change",
		"on_cancel": [
			"forwarding.custom_methods.update_cost_table_in_operations_on_cancle",
			"forwarding.job_events.on_sales_invoice_change",
		],
		"on_update_after_submit": "forwarding.job_events.on_sales_invoice_change",
		"on_trash": "forwarding.job_events.on_sales_invoice_change",
	},
    "Purchase Invoice": {
		"validate": "forwarding.subscription.enforce_limit",
		"on_update": [
			"forwarding.custom_methods.update_cost_table_in_operations",
			"forwarding.job_events.on_linked_change",
		],
		"on_submit": "forwarding.job_events.on_linked_change",
		"on_cancel": [
			"forwarding.custom_methods.update_cost_table_in_operations_on_cancle",
			"forwarding.job_events.on_linked_change",
		],
		"on_update_after_submit": "forwarding.job_events.on_linked_change",
		"on_trash": "forwarding.job_events.on_linked_change",
	},
	"Payment Entry": {
		"on_update": "forwarding.job_events.clear_payment_party_cache",
		"on_trash": "forwarding.job_events.clear_payment_party_cache",
		"on_submit": "forwarding.job_events.on_payment_change",
		"on_cancel": "forwarding.job_events.on_payment_change",
	},
	"Journal Entry": {
		"on_submit": "forwarding.job_events.on_payment_change",
		"on_cancel": "forwarding.job_events.on_payment_change",
	},
	"Operations": {
		"validate": [
			"forwarding.subscription.enforce_limit",
			"forwarding.child_tables.apply",
		],
		"on_update": "forwarding.job_events.on_job_change",
		"on_update_after_submit": "forwarding.job_events.on_job_change",
		"on_cancel": "forwarding.job_events.on_job_change",
		"on_trash": "forwarding.job_events.on_job_change",
	},
	"Transportation": {
		"validate": "forwarding.child_tables.apply",
		"on_update": "forwarding.job_events.on_linked_change",
		"on_trash": "forwarding.job_events.on_linked_change",
	},
	"Custom Clearance": {
		"validate": "forwarding.child_tables.apply",
		"on_update": "forwarding.job_events.on_linked_change",
		"on_trash": "forwarding.job_events.on_linked_change",
	},
	"Freight Voucher": {
		"validate": "forwarding.subscription.enforce_limit",
	},
	"Freight Tracking": {
		"validate": "forwarding.subscription.enforce_limit",
	},
	"Customer": {
		"before_insert": "forwarding.naming.set_customer_code",
		"on_update": "forwarding.job_events.on_customer_change",
		"on_trash": "forwarding.job_events.on_customer_change",
	},
	"Quote": {
		"on_update": "forwarding.job_events.on_quote_change",
		"on_trash": "forwarding.job_events.on_quote_change",
	},
	"Contact": {
		"on_update": "forwarding.job_events.on_party_detail_change",
		"on_trash": "forwarding.job_events.on_party_detail_change",
	},
	"Address": {
		"on_update": "forwarding.job_events.on_party_detail_change",
		"on_trash": "forwarding.job_events.on_party_detail_change",
	},
	"File": {
		"after_insert": "forwarding.job_events.on_file_change",
		"on_trash": "forwarding.job_events.on_file_change",
	},
	"Supplier": {
		"before_insert": "forwarding.naming.set_supplier_code",
		"validate": "forwarding.supplier.validate",
		"on_update": "forwarding.job_events.on_supplier_change",
		"on_trash": "forwarding.job_events.on_supplier_change",
	},
	"Vehicle": {
		"on_update": "forwarding.job_events.on_fleet_change",
		"on_trash": "forwarding.job_events.on_fleet_change",
	},
	"Driver": {
		"on_update": "forwarding.job_events.on_fleet_change",
		"on_trash": "forwarding.job_events.on_fleet_change",
	},
	"Item Price": {
		"on_update": "forwarding.job_events.on_item_price_change",
		"on_trash": "forwarding.job_events.on_item_price_change",
	},
	# The custom_ui records forwarding.api.ui_config reads. Child rows (tabs,
	# wizard fields) are saved through their parent, which fires these; the
	# Dashboard Tab entry covers a row saved on its own.
	"Custom UI Dashboard": {
		"on_update": "forwarding.api.ui_config.clear_cache",
		"on_trash": "forwarding.api.ui_config.clear_cache",
	},
	"Custom UI Dashboard Tab": {
		"on_update": "forwarding.api.ui_config.clear_cache",
		"on_trash": "forwarding.api.ui_config.clear_cache",
	},
	"Custom UI Wizard Layout": {
		"on_update": "forwarding.api.ui_config.clear_cache",
		"on_trash": "forwarding.api.ui_config.clear_cache",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"forwarding.tasks.all"
# 	],
# 	"daily": [
# 		"forwarding.tasks.daily"
# 	],
# 	"hourly": [
# 		"forwarding.tasks.hourly"
# 	],
# 	"weekly": [
# 		"forwarding.tasks.weekly"
# 	]
# 	"monthly": [
# 		"forwarding.tasks.monthly"
# 	]
# }

scheduler_events = {
	"daily": [
		"forwarding.tasks.send_shipment_reminders",
	],
}

# Testing
# -------

# before_tests = "forwarding.install.before_tests"

# Overriding Methods
# ------------------------------
#
# The website Contact Us endpoint is a Guest path that can create Leads
# (ERPNext's override inserts a Lead + Opportunity). Route both dotted paths
# through the guarded version; see forwarding/contact_us.py.
override_whitelisted_methods = {
	"frappe.www.contact.send_message": "forwarding.contact_us.send_message",
	"erpnext.templates.utils.send_message": "forwarding.contact_us.send_message",
	"frappe.utils.print_format.download_pdf": "forwarding.print_pdf.download_pdf",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "forwarding.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

