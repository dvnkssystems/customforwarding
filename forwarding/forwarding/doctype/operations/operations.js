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
// ---------------------------------------------------------------------------
// Job form behaviour ported from the Bridge LCS job screen:
//   - Activity Code seeds the service checkboxes (which gate the tabs)
//   - the Package grid derives volume / total weight and rolls up to totals
//   - the Container grid gets bulk-create and paste-import helpers
// ---------------------------------------------------------------------------

const SERVICE_TYPE_FIELD = {
	"Freight Forwarding": "svc_freight_forwarding",
	"Customs Clearance": "svc_customs_clearance",
	"Transportation": "svc_transportation",
	"Trading": "svc_trading",
	"Value Added Services": "svc_packing_relocation",
};

function calculate_package_totals(frm) {
	let qty = 0, volume = 0, weight = 0, chargeable = 0;

	(frm.doc.package_details || []).forEach(row => {
		row.volume = flt(row.quantity) * (flt(row.length) * flt(row.width) * flt(row.height)) / 1000000;
		row.total_weight = flt(row.quantity) * flt(row.weight);

		qty += flt(row.quantity);
		volume += flt(row.volume);
		weight += flt(row.total_weight);
		chargeable += flt(row.chargeable_weight);
	});

	frm.set_value("total_package_qty", qty);
	frm.set_value("total_package_volume", volume);
	frm.set_value("total_package_weight", weight);
	frm.set_value("total_chargeable_weight", chargeable);
	frm.refresh_field("package_details");
}

frappe.ui.form.on("Operations", {
	activity_code: function (frm) {
		if (!frm.doc.activity_code) return;

		frappe.db.get_value("Freight Activity Code", frm.doc.activity_code, "service_type")
			.then(r => {
				const field = SERVICE_TYPE_FIELD[r.message && r.message.service_type];
				if (field) frm.set_value(field, 1);
			});
	},

	// row deletions fire on the parent form, not on the child doctype
	package_details_remove: calculate_package_totals,

	refresh: function (frm) {
		frm.add_custom_button(__("Add Containers"), () => bulk_add_containers(frm), __("Container"));
		frm.add_custom_button(__("Import Containers"), () => import_containers(frm), __("Container"));
	},
});

frappe.ui.form.on("Package", {
	quantity: calculate_package_totals,
	weight: calculate_package_totals,
	length: calculate_package_totals,
	width: calculate_package_totals,
	height: calculate_package_totals,
	chargeable_weight: calculate_package_totals,
});

// Bulk-create identical container rows, mirroring the LCS "Count -> Create" control.
function bulk_add_containers(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Add Containers"),
		fields: [
			{ fieldname: "size", fieldtype: "Select", label: __("Container"), options: "\n20\n40\n45" },
			{ fieldname: "container_type", fieldtype: "Link", label: __("Container Type"), options: "Container Type" },
			{ fieldname: "dg_shipment_type", fieldtype: "Select", label: __("Shipment Type"), options: "\nDG\nNon DG" },
			{ fieldname: "cb", fieldtype: "Column Break" },
			{ fieldname: "terminal", fieldtype: "Link", label: __("Terminal"), options: "Freight Terminal" },
			{ fieldname: "qty_type", fieldtype: "Select", label: __("Qty Type"),
			  options: "\nBag\nBox\nCarton\nDrum\nPallet\nPer Container\nPer Kg\nPer Shipment\nTank\nUnit" },
			{ fieldname: "count", fieldtype: "Int", label: __("Count"), reqd: 1, default: 1,
			  description: __("Maximum 30 rows per batch") },
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			const count = cint(values.count);
			if (count < 1 || count > 30) {
				frappe.msgprint(__("Enter a count between 1 and 30."));
				return;
			}
			for (let i = 0; i < count; i++) {
				const row = frm.add_child("container_details");
				["size", "container_type", "dg_shipment_type", "terminal", "qty_type"].forEach(f => {
					if (values[f]) row[f] = values[f];
				});
			}
			frm.refresh_field("container_details");
			dialog.hide();
			frappe.show_alert({ message: __("Added {0} containers", [count]), indicator: "green" });
		},
	});
	dialog.show();
}

// Paste-in equivalent of the LCS "Import Container" tab (Excel upload).
function import_containers(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Import Containers"),
		fields: [
			{
				fieldname: "help", fieldtype: "HTML",
				options: `<p>${__("Paste one container per line, comma separated:")}</p>
					<pre>container_no, size, type, seal_no, weight, volume, tare_weight, vgm</pre>`,
			},
			{ fieldname: "data", fieldtype: "Small Text", label: __("Rows"), reqd: 1 },
		],
		primary_action_label: __("Import"),
		primary_action(values) {
			const lines = (values.data || "").split("\n").map(l => l.trim()).filter(Boolean);
			if (!lines.length) {
				frappe.msgprint(__("Nothing to import."));
				return;
			}
			lines.forEach(line => {
				const c = line.split(",").map(v => v.trim());
				const row = frm.add_child("container_details");
				row.container_no = c[0] || "";
				row.size = c[1] || "";
				row.container_type = c[2] || "";
				row.seal_no = c[3] || "";
				row.weight = flt(c[4]);
				row.volume = flt(c[5]);
				row.tare_weight = flt(c[6]);
				row.vgm = flt(c[7]);
			});
			frm.refresh_field("container_details");
			dialog.hide();
			frappe.show_alert({ message: __("Imported {0} containers", [lines.length]), indicator: "green" });
		},
	});
	dialog.show();
}
