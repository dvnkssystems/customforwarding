// Copyright (c) 2021, FirstERP and contributors
// For license information, please see license.txt

frappe.ui.form.on('Port', {
	refresh: function(frm) {
		cur_frm.fields_dict['country'].get_query = function(doc, cdt, cdn) {
			return {
				filters:{
					"is_country": 1,
				}
			}
		}
	 }
});
