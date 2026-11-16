# Copyright (c) 2026, DVNKS Systems and contributors
"""Reports and screens missing from the app menu (Royal Eagle, T-26-11-00051).

Shubham's list named 7 DocTypes and 15 reports. Each one is added to the menu
when it exists on the site and works there. A site that doesn't have one skips
it. An entry that already opens the same report or DocType is left as it is,
so running this twice changes nothing.

- Reports go under the Reports group, after the ones already there. The
  three saved job lists (Askar - Riyadh jobs, Dammam Jobs, SHARAFU JOBS) open
  through forwarding.report_runner.
- Reports whose code is only an empty placeholder (no implementation was
  ever handed over) are left out, so the menu shows no empty reports.
- DocTypes go under Freight Operations. A child table such as Payment Items
  has no list of its own and is skipped.
- Estimation Vs Actual Summary V3 is reloaded from its file first. It was a
  Query Report without filters, and any blank filter made it fail.
"""

import frappe

from forwarding.patches.v1_0.b5_sidebar_cleanup import ITEM, top_group

# (report name, menu label), in menu order.
REPORTS = [
	("Askar - Riyadh jobs", "Riyadh Jobs (Askar)"),
	("Dammam Jobs", "Dammam Jobs"),
	("SHARAFU JOBS", "Sharafu Jobs"),
	("Detailed Job Report", "Detailed Job Report"),
	("Estimated Job Report Summary", "Estimated Job Summary"),
	("Estimated Job Report Detailed", "Estimated Job Detailed"),
	("Estimation Vs Actual Summary V3", "Estimation vs Actual Summary V3"),
	("Summary V3", "Summary V3"),
	("Summary Report - Estimation Vs Actual", "Summary - Estimation vs Actual"),
	("Summary Report - Estimation Vs Actual Exp", "Summary - Estimation vs Actual (Expense)"),
	("Detailed Job Report with Expense", "Detailed Job Report with Expense"),
	("Detailed Job Report with Estimation VS Actual", "Detailed Job Report with Estimation vs Actual"),
	("SOA", "Statement of Account (SOA)"),
	("VAT Report", "VAT Report"),
	("Filter Test", "Filter Test"),
]

# (DocType, menu label)
DOCTYPES = [
	("Operations", "Freight Jobs"),
	("Container Booking Request", "Container Bookings"),
	("Custom Clearance", "Customs Clearance"),
	("Transportation", "Transport Orders"),
	("Cost Template", "Cost Templates"),
	("Delivery Challan", "Delivery Challans"),
	("Payment Items", "Payment Items"),
]

# The placeholder that a Script Report gets when it has no code (see
# forwarding/forwarding/report/*/: "PLACEHOLDER — this report has no
# implementation").
PLACEHOLDER = "PLACEHOLDER"


def execute():
	reload_v3()
	if not frappe.db.exists("DocType", ITEM):
		return
	reports = top_group("Reports")
	if reports:
		for report, label in REPORTS:
			if runnable(report) and not frappe.db.exists(ITEM, {"target_report": report, "is_active": 1}):
				add(reports, label, "Report", target_report=report)
	operations = top_group("Freight Operations")
	if operations:
		for doctype, label in DOCTYPES:
			if listable(doctype) and not frappe.db.exists(
				ITEM, {"item_type": "Link", "target_doctype": doctype, "is_active": 1}
			):
				add(operations, label, "Link", target_doctype=doctype)


def reload_v3():
	"""The file version replaces the Query Report record of the same name."""
	frappe.reload_doc("forwarding", "report", "estimation_vs_actual_summary_v3", force=True)


def runnable(name):
	row = frappe.db.get_value("Report", name, ["report_type", "is_standard", "module", "disabled"], as_dict=True)
	if not row or row.disabled:
		return False
	if row.report_type == "Script Report" and row.is_standard == "Yes":
		path = script_path(name, row.module)
		if not path:
			return False
		with open(path) as f:
			return PLACEHOLDER not in f.read()
	return True


def script_path(name, module):
	"""The report's .py file, or None when no installed app has it."""
	import os

	try:
		app = frappe.local.module_app[frappe.scrub(module)]
	except KeyError:
		return None
	folder = frappe.scrub(name)
	path = frappe.get_app_path(app, frappe.scrub(module), "report", folder, folder + ".py")
	return path if os.path.exists(path) else None


def listable(doctype):
	return bool(frappe.db.get_value("DocType", {"name": doctype, "istable": 0}))


def add(parent, label, item_type, **target):
	orders = frappe.get_all(ITEM, filters={"parent_item": parent}, pluck="sort_order")
	group_label = frappe.db.get_value(ITEM, parent, "item_label")
	name = f"FF {group_label} / {label}"
	if frappe.db.exists(ITEM, name):
		frappe.db.set_value(ITEM, name, {"is_active": 1, "parent_item": parent, **target})
		return
	frappe.get_doc(
		{
			"doctype": ITEM,
			"name": name,
			"item_label": label,
			"item_type": item_type,
			"parent_item": parent,
			"sort_order": max([0, *(o or 0 for o in orders)]) + 1,
			"is_active": 1,
			**target,
		}
	).insert(ignore_permissions=True)
