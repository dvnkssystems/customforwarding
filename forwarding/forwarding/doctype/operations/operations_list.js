frappe.listview_settings['Operations'] = {
	hide_name_column: true,
	add_fields: ["billing_status", "is_favorite", "is_trashed", "operations_status"],

	// Colour the billing status in the list
	get_indicator: function (doc) {
		const map = {
			"No Invoice": "gray",
			"Cost Sheet Pending": "orange",
			"Pending Billing": "blue",
			"Billed": "green",
		};
		const colour = map[doc.billing_status] || "gray";
		const label = doc.billing_status || "No Invoice";
		return [__(label), colour, "billing_status,=," + label];
	},

	onload: function (listview) {
		// Hide trashed jobs by default
		if (!frappe.route_options || !("is_trashed" in frappe.route_options)) {
			listview.filter_area.add([[listview.doctype, "is_trashed", "=", 0]]);
		}

		// Quick-filter "tabs" as menu actions
		const tabs = {
			"All Active": { is_trashed: 0 },
			"Favorites": { is_favorite: 1, is_trashed: 0 },
			"Trashed": { is_trashed: 1 },
		};
		Object.keys(tabs).forEach((label) => {
			listview.page.add_action_item(__(label), () => {
				listview.filter_area.clear();
				const f = tabs[label];
				Object.keys(f).forEach((fn) =>
					listview.filter_area.add([[listview.doctype, fn, "=", f[fn]]])
				);
			});
		});

		// Billing-status KPI counters in the page header
		frappe.call({
			method: "forwarding.api.get_billing_status_counts",
			callback: function (r) {
				if (!r.message) return;
				const c = r.message;
				function kpi(label, val, colour) {
					return `<div style="border:1px solid var(--border-color);border-radius:8px;padding:8px 14px;min-width:120px;">
						<div style="font-size:11px;color:var(--text-muted);">${frappe.utils.escape_html(label)}</div>
						<div style="font-size:20px;font-weight:600;color:${colour};">${val}</div></div>`;
				}
				const html = `
					<div class="freight-kpi-cards" style="display:flex;gap:10px;margin:8px 0;flex-wrap:wrap;">
						${kpi("No Invoice", c["No Invoice"] || 0, "#6c7680")}
						${kpi("Cost Sheet Pending", c["Cost Sheet Pending"] || 0, "#cb7c00")}
						${kpi("Pending Billing", c["Pending Billing"] || 0, "#1f6fd6")}
						${kpi("Billed", c["Billed"] || 0, "#2e7d32")}
					</div>`;
				$(listview.page.main).find(".freight-kpi-cards").remove();
				$(listview.page.main).prepend(html);
			},
		});
	},
};
