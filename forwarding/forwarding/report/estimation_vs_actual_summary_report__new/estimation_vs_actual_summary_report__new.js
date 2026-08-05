// Copyright (c) 2026, Forwarding and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Estimation VS Actual Summary Report_-NEW"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -6),
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
			fieldname: "date_basis",
			label: __("Date Basis"),
			fieldtype: "Select",
			options: "Job Date\nPosting Date",
			default: "Job Date",
			// Job Date bounds the jobs and leaves their postings unclipped, so a
			// late posting still shows. Posting Date bounds the ledger instead —
			// what was recorded in the period, whenever the job opened.
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
			get_query() {
				const company = frappe.query_report.get_filter_value("company");
				return company ? { filters: { company } } : {};
			},
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "mode_of_shipment",
			label: __("Mode Of Shipment"),
			fieldtype: "Link",
			options: "Mode Of Shipment",
		},
		{
			fieldname: "job",
			label: __("Job"),
			fieldtype: "Link",
			options: "Operations",
			// Trashed jobs are not worth offering, and scoping the lookup to the
			// company already chosen keeps a 1,400-row list usable.
			get_query() {
				const company = frappe.query_report.get_filter_value("company");
				const filters = { is_trashed: 0 };
				if (company) filters.company = company;
				return { filters };
			},
		},
		{
			fieldname: "include_open",
			label: __("Include Open Jobs"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "only_with_variance",
			label: __("Only Jobs With A Variance"),
			fieldtype: "Check",
		},
		{
			fieldname: "only_untagged",
			label: __("Only Jobs With No Ledger Entry"),
			fieldtype: "Check",
			// The tagging check: these are jobs no GL Entry points at through its
			// Project field, which reads identically to a job that earned nothing.
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Variance carries the message of the report, so it is the one column
		// that is coloured: green beat the estimate, red fell short.
		if (column.fieldname === "variance" && data && data.variance) {
			const colour = data.variance > 0 ? "green" : "red";
			value = `<span style="color:${colour}">${value}</span>`;
		}

		// A negative actual profit is worth seeing without reading the number —
		// but only when the job has actually been billed. Unbilled ones are
		// muted instead, because a red loss there means "not invoiced yet".
		if (column.fieldname === "actual_profit" && data && data.actual_profit < 0) {
			value = data.billed
				? `<span style="color:red">${value}</span>`
				: `<span style="color:var(--text-light)" title="${__("Nothing billed on this job yet")}">${value}</span>`;
		}

		// Same reasoning for the variance.
		if (column.fieldname === "variance" && data && !data.billed && data.actual_expense) {
			value = `<span style="color:var(--text-light)">${value}</span>`;
		}

		return value;
	},
};
