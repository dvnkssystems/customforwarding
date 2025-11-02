// Copyright (c) 2021, FirstERP and contributors
// For license information, please see license.txt

frappe.ui.form.on('Operations', {
	add_template: function(frm) {
		if (frm.doc.parcel_template) {
			frappe.model.with_doc("Shipment Parcel Template", frm.doc.parcel_template, () => {
				let parcel_template = frappe.model.get_doc("Shipment Parcel Template", frm.doc.parcel_template);
				let row = frappe.model.add_child(frm.doc, "Shipment Parcel", "shipment_parcel");
				row.length = parcel_template.length;
				row.width = parcel_template.width;
				row.height = parcel_template.height;
				row.weight = parcel_template.weight;
				frm.refresh_fields("shipment_parcel");
			});
		}
	},
	onload: function(frm){

	}

	// 	validate: function (frm) {
	// 	frm.call({
	// 		doc: frm.doc,
	// 		method: "create_project",
	// 		callback: function () {
	// 			frm.refresh();
	// 			frm.toolbar.refresh();
	// 		}
	// 	});
	// }
});

//custom button to create sales invoice
// frappe.ui.form.on("Operations",{
//     onload:function(frm){
//         console.log("Creating Button")
// 		cur_frm.add_custom_button()
// 		frm.add_custom_button(__('Sales Invoice'), function() {
// 				frappe.model.open_mapped_doc({
// 					method: "forwarding.forwarding.doctype.operations.operations.make_sales_invoice",
// 					frm: cur_frm,
// 				})
// 			}, __('Create'));   
// 		frm.page.set_inner_btn_group_as_primary(__('Create'));     
//     }
// })

frappe.ui.form.on('Operations', {
    refresh: function(frm) {
      frm.add_custom_button(__('Sales Invoice'), function(){
        frappe.model.open_mapped_doc({
			method: "forwarding.forwarding.doctype.operations.operations.make_sales_invoice",
			frm: cur_frm,
		})
    }, __("Create"));
	if(cur_frm.doc.freight_forwarding==1){
	frm.add_custom_button(__('Freight'), function(){
        frappe.model.open_mapped_doc({
			method: "forwarding.forwarding.doctype.operations.operations.make_freight",
			frm: cur_frm,
		})
	}, __("Create"));
	}
	if(cur_frm.doc.custom_clearance==1){
	frm.add_custom_button(__('Custom Clearance'), function(){
        frappe.model.open_mapped_doc({
			method: "forwarding.forwarding.doctype.operations.operations.make_custom_clearance",
			frm: cur_frm,
		})
	}, __("Create"));
	}
	if(cur_frm.doc.transport==1){	
	frm.add_custom_button(__('Transportation'), function(){
        frappe.model.open_mapped_doc({
			method: "forwarding.forwarding.doctype.operations.operations.make_transportaion",
			frm: cur_frm,
		})
	}, __("Create"));
	}	

	frm.add_custom_button(__('Purchase Invoice'), function(){
        frappe.model.open_mapped_doc({
			method: "forwarding.forwarding.doctype.operations.operations.make_purchase_invoice",
			frm: cur_frm,
		})
	}, __("Create"));
	frm.add_custom_button(__('Container Booking Request'), function(){
        frappe.model.open_mapped_doc({
			method: "forwarding.forwarding.doctype.operations.operations.make_booking",
			frm: cur_frm,
		})
    }, __("Create"));
	
	hide_name_column: true
  }
});