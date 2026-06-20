frappe.listview_settings['Freight Job Status'] = {
	add_fields: ["is_muted", "status_text"],
	get_indicator: function (doc) {
		if (doc.is_muted) return [__("Muted"), "gray", "is_muted,=,1"];
		if (doc.status_text) return [__("Updated"), "green", "is_muted,=,0"];
		return [__("Pending"), "orange", "status_text,=,"];
	},
	onload: function (listview) {
		listview.page.add_actions_menu_item(__("Master Status Update"), () => {
			const jobs = listview.get_checked_items(true);
			if (!jobs.length) {
				frappe.msgprint(__("Select at least one row."));
				return;
			}
			const d = new frappe.ui.Dialog({
				title: __("Master Status Update"),
				fields: [
					{ fieldname: "status_text", label: __("Status"), fieldtype: "Data", reqd: 1 },
					{ fieldname: "status_date", label: __("Status Date"), fieldtype: "Datetime" },
					{ fieldname: "bayan_no", label: __("Bayan No"), fieldtype: "Data" },
				],
				primary_action_label: __("Update"),
				primary_action(values) {
					frappe.call({
						method: "forwarding.api.master_status_update",
						args: {
							jobs: listview.get_checked_items().map((r) => r.freight_job),
							status_text: values.status_text,
							status_date: values.status_date,
							bayan_no: values.bayan_no,
						},
						callback: (r) => {
							frappe.show_alert(__("Updated {0} jobs", [r.message.updated]));
							d.hide();
							listview.refresh();
						},
					});
				},
			});
			d.show();
		});
	},
};
