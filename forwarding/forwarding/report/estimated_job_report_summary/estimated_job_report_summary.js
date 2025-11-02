frappe.query_reports["Estimated Job Report Summary"] = {
	"filters": [
		{
			"fieldname":"from_date",
			"label": __("From"),
			"fieldtype": "Date",
			"default": frappe.utils.nowdate(),
			"reqd": 1
		},
		{
			"fieldname":"to_date",
			"label": __("To"),
			"fieldtype": "Date",
			"default": frappe.utils.nowdate(),
			"reqd": 1
		},
	]
}