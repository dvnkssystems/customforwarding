// Copyright (c) 2021, FirstERP and contributors
// For license information, please see license.txt

frappe.ui.form.on('Custom Clearance', {
	make_dashboard: function(frm) {
		// let max_count = frm.doc.__onload.max_count;
		// let opening_invoices_summary = frm.doc.__onload.opening_invoices_summary;
		// if(!$.isEmptyObject(opening_invoices_summary)) {

			let section = frm.dashboard.add_section(
				frappe.render_template('cc', {
					data:cur_frm.doc.activity_template_table,
					a:"Ganya"
					// max_count: 1
				})
			);
			frm.dashboard.show();
		// }
	},
	refresh: function(frm) {
		frm.trigger("make_dashboard");
	}
});

frappe.ui.form.on('Custom Clearance', {
	activity_template: function(frm) {
		if (frm.doc.activity_template) {
			frappe.call({
				doc: frm.doc,
				method: "get_template",
				freeze: true,
				callback: function(r) {
					if (!r.exc) {
						frm.refresh_fields();
					}
				}
			});
		}
	}
});	