// Copyright (c) 2026, DVNKS Systems and contributors
/* eslint-disable */

frappe.query_reports["Estimation Vs Actual Summary V3"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "basis",
			label: __("Date Basis"),
			fieldtype: "Select",
			options: "Job Date\nPosting Date",
			default: "Job Date",
		},
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "operations", label: __("Job"), fieldtype: "Link", options: "Operations" },
	],
};
