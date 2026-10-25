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

	},

	// Shipment Type options depend on the mode, so a type picked for the old
	// mode is cleared rather than left behind to fail validation on save.
	mode_of_shipment: async function(frm) {
		if (!frm.doc.shipment_type) return;
		const r = await frappe.db.get_value("Shipment Type", frm.doc.shipment_type, "mode_of_shipment");
		const mode = r && r.message && r.message.mode_of_shipment;
		if (mode && mode !== frm.doc.mode_of_shipment) {
			frm.set_value("shipment_type", "");
		}
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
	// Container Booking Request is kept (make_booking still works) but its
	// button is hidden until operations start using it again.
	
	hide_name_column: true
  }
});
// ---------------------------------------------------------------------------
// Job form behaviour ported from the Bridge LCS job screen:
//   - Services tick the service checkboxes (which gate the tabs), and the
//     Services picker offers only codes that suit the job (M-05, M-06, R2-23)
//   - the Package grid derives volume / total weight and rolls up to totals
//   - the Container grid gets bulk-create and paste-import helpers
// ---------------------------------------------------------------------------

// As forwarding.services.SERVICE_TYPE_FIELD; the server sets the same boxes on save.
const SERVICE_TYPE_FIELD = {
	"Freight Forwarding": "svc_freight_forwarding",
	"Customs Clearance": "svc_customs_clearance",
	"Transportation": "svc_transportation",
	"Trading": "svc_trading",
	"Warehousing": "svc_warehousing",
	"Packing & Relocation": "svc_packing_relocation",
};

// The job's chosen Scopes of Work, in order.
function scope_names(doc) {
	return (doc.scopes_of_work || []).map(r => r.scope_of_work).filter(Boolean);
}

// Codes that suit the job's mode, job type and scopes of work.
function services_query(doc) {
	const filters = {
		mode_of_shipment: doc.mode_of_shipment || "",
		job_type: doc.job_type || "",
		scopes_of_work: JSON.stringify(scope_names(doc)),
		// A service already on the job drops out of the list (R3-25).
		exclude: JSON.stringify((doc.services || []).map((r) => r.activity_code).filter(Boolean)),
	};
	// A form without the table (an older meta) still sends its one scope.
	if (!doc.scopes_of_work) filters.scope_of_work = doc.scope_of_work || "";
	return { query: "forwarding.services.activity_code_query", filters };
}

// As forwarding.services.SCOPE_FLAGS: the old flags the detail sections read.
const SCOPE_FLAGS = {
	freight_forwarding: "Freight Forwarding",
	custom_clearance: "Customs Clearance",
	transport: "Transportation",
};

// Only what the chosen scopes allow shows on the form: the service boxes and
// the detail sections. The server sets the same flags on save; the form sets
// them only when the scopes change, so opening a job leaves it unchanged.
function apply_scopes(frm, set_flags) {
	const scopes = scope_names(frm.doc);
	// The tick-boxes follow the Services list and stay hidden (R3-26): the
	// list is the one place services are chosen.
	Object.values(SERVICE_TYPE_FIELD).forEach(field => frm.toggle_display(field, false));
	if (!scopes.length && !frm.doc.scope_of_work) return;
	frappe.call({
		method: "forwarding.services.scope_service_types",
		args: { scopes: JSON.stringify(scopes.length ? scopes : [frm.doc.scope_of_work]) },
	}).then(r => {
		const allowed = r && r.message;
		const offers = type => !Array.isArray(allowed) || allowed.includes(type);
		if (!set_flags || !Array.isArray(allowed)) return;
		Object.entries(SCOPE_FLAGS).forEach(([field, type]) => {
			const value = offers(type) ? "1" : "0";
			if (String(frm.doc[field] ?? "") !== value) frm.set_value(field, value);
		});
	});
}

// Tick each service box exactly when a chosen code is of its type.
function tick_service_boxes(frm) {
	const codes = (frm.doc.services || []).map(r => r.activity_code).filter(Boolean);
	if (!codes.length) return;
	frappe.db.get_list("Freight Activity Code", {
		filters: { name: ["in", codes] },
		fields: ["name", "service_type"],
	}).then(r => {
		const rows = Array.isArray(r) ? r : (r && r.message) || [];
		const types = new Set(rows.map(row => row.service_type));
		Object.entries(SERVICE_TYPE_FIELD).forEach(([type, field]) => {
			const value = types.has(type) ? 1 : 0;
			if (cint(frm.doc[field]) !== value) frm.set_value(field, value);
		});
	});
}

// kg per cubic metre for volumetric weight (IATA 1:6000), as on the server.
const VOLUMETRIC_FACTOR = 167;

// Mirrors Operations.calculate_package_totals / set_cargo_from_packages.
function calculate_package_totals(frm) {
	let qty = 0, volume = 0, weight = 0, chargeable = 0;
	const rows = frm.doc.package_details || [];

	rows.forEach(row => {
		row.volume = flt(row.quantity) * (flt(row.length) * flt(row.width) * flt(row.height)) / 1000000;
		row.total_weight = flt(row.quantity) * flt(row.weight);
		row.chargeable_weight = Math.max(row.total_weight, row.volume * VOLUMETRIC_FACTOR);

		qty += flt(row.quantity);
		volume += flt(row.volume);
		weight += flt(row.total_weight);
		chargeable += flt(row.chargeable_weight);
	});

	frm.set_value("total_package_qty", qty);
	frm.set_value("total_package_volume", volume);
	frm.set_value("total_package_weight", weight);
	frm.set_value("total_chargeable_weight", chargeable);
	if (rows.length) {
		// The header cargo figures follow the rows while there are any.
		frm.set_value("packages", String(qty));
		frm.set_value("no_of_pieces", Math.round(qty));
		frm.set_value("gross_weight", weight);
		frm.set_value("cbm", flt(volume, 3));
		frm.set_value("volume", flt(volume, 3));
		frm.set_value("chargable_weight", chargeable);
	}
	frm.refresh_field("package_details");
}

frappe.ui.form.on("Operations", {
	services: tick_service_boxes,
	scopes_of_work: frm => apply_scopes(frm, true),

	// row deletions fire on the parent form, not on the child doctype
	package_details_remove: calculate_package_totals,

	refresh: function (frm) {
		frm.set_query("services", services_query);
		frm.set_query("activity_code", "services", services_query);
		apply_scopes(frm);
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

// ---------------------------------------------------------------------------
// Prints: a delivery note for chosen containers, and the arrival notice.
// ---------------------------------------------------------------------------

frappe.ui.form.on("Operations", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Delivery Note"), () => print_delivery_note(frm), __("Print"));
		frm.add_custom_button(__("Arrival Notice"), () => open_job_print(frm, "Arrival Notice"), __("Print"));
	},
});

function open_job_print(frm, format, extra) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the job before printing."));
		return;
	}
	const params = new URLSearchParams({ doctype: frm.doctype, name: frm.doc.name, format, ...(extra || {}) });
	window.open(`/printview?${params.toString()}`, "_blank");
}

// With several containers, ask which ones this delivery note covers.
function print_delivery_note(frm) {
	const rows = frm.doc.container_details || [];
	if (rows.length < 2) {
		open_job_print(frm, "Job Delivery Note");
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Delivery Note"),
		fields: [
			{
				fieldname: "containers",
				fieldtype: "MultiCheck",
				label: __("Containers on this delivery"),
				columns: 2,
				options: rows.map((row) => ({
					label: [row.container_no || __("Row {0}", [row.idx]), row.size && `${row.size}'`, row.container_type]
						.filter(Boolean)
						.join(" · "),
					value: row.name,
					checked: 1,
				})),
			},
		],
		primary_action_label: __("Print"),
		primary_action(values) {
			const picked = values.containers || [];
			if (!picked.length) {
				frappe.msgprint(__("Select at least one container."));
				return;
			}
			dialog.hide();
			open_job_print(frm, "Job Delivery Note", { containers: picked.join(",") });
		},
	});
	dialog.show();
}

// ---------------------------------------------------------------------------
// Sections that only apply to some modes / job types. Changing the mode or job
// type never clears data: a section that still holds data stays visible. The
// user is asked first, and saying no puts the old value back.
// ---------------------------------------------------------------------------

const SECTION_RULES = {
	mode_of_shipment: [
		{ label: __("Containers"), fields: ["container_details"], applies: (v) => v !== "Air" },
		{ label: __("Flight Number / Air Line"), fields: ["flight_number", "air_line"], applies: (v) => v === "Air" },
		{
			label: __("Vessel / Voyage / Shipping Line"),
			fields: ["vessel_name", "voyage_number", "shipping_line"],
			applies: (v) => v === "Sea",
		},
	],
	job_type: [{ label: __("Cut-offs"), fields: ["cutoffs"], applies: (v) => v === "Export" }],
};

function has_data(frm, fieldname) {
	const value = frm.doc[fieldname];
	return Array.isArray(value) ? value.length > 0 : !!value;
}

function remember_section_values(frm) {
	frm._section_values = { mode_of_shipment: frm.doc.mode_of_shipment, job_type: frm.doc.job_type };
}

function confirm_section_change(frm, trigger) {
	const previous = (frm._section_values || {})[trigger];
	const value = frm.doc[trigger];
	if (frm._reverting || previous === undefined || previous === value) {
		remember_section_values(frm);
		return;
	}

	const affected = SECTION_RULES[trigger]
		.filter((rule) => rule.applies(previous) && !rule.applies(value))
		.filter((rule) => rule.fields.some((f) => has_data(frm, f)))
		.map((rule) => rule.label);
	if (!affected.length) {
		remember_section_values(frm);
		return;
	}

	frappe.confirm(
		__("{0} does not use {1}, but this job already has data there. The data is kept and stays visible until you clear it. Continue?", [
			value || __("this setting"),
			affected.join(", "),
		]),
		() => remember_section_values(frm),
		() => {
			frm._reverting = true;
			frm.set_value(trigger, previous).then(() => {
				frm._reverting = false;
				remember_section_values(frm);
			});
		}
	);
}

frappe.ui.form.on("Operations", {
	refresh: remember_section_values,
	mode_of_shipment: (frm) => confirm_section_change(frm, "mode_of_shipment"),
	job_type: (frm) => confirm_section_change(frm, "job_type"),
});

// ---------------------------------------------------------------------------
// Cut-offs: an export job with none starts with the milestones for its mode
// (Sea: all but AES unless bound for the US; Air: SI Deadline + Cargo Cut-off).
// The server adds the same rows when the job is inserted (Operations.
// before_insert); adding them here shows them before the first save. Deadline
// is optional, so the rows can be saved undated. A job that already has
// cut-offs is left alone.
// ---------------------------------------------------------------------------

async function prefill_cutoffs(frm) {
	if (frm.doc.docstatus !== 0 || frm.doc.job_type !== "Export" || (frm.doc.cutoffs || []).length) return;
	if (!frm.doc.mode_of_shipment) return;

	const r = await frappe.call({
		method: "forwarding.api.job_360.default_cutoffs",
		args: { mode_of_shipment: frm.doc.mode_of_shipment, destination_country: frm.doc.destination_country },
	});
	const milestones = (r && r.message) || [];
	if (!milestones.length || (frm.doc.cutoffs || []).length) return;

	milestones.forEach((milestone) => frm.add_child("cutoffs", { milestone }));
	frm.refresh_field("cutoffs");
	frappe.show_alert({ message: __("Cut-offs added for this export job: enter each Deadline, or remove the rows you do not need."), indicator: "blue" }, 7);
}

frappe.ui.form.on("Operations", {
	refresh: (frm) => frm.is_new() && prefill_cutoffs(frm),
	job_type: prefill_cutoffs,
	mode_of_shipment: prefill_cutoffs,
});

// Shared child-table rules (the server applies the same in forwarding.child_tables).
frappe.ui.form.on("Document Table", {
	attach(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.attach && row.received !== "Yes") {
			frappe.model.set_value(cdt, cdn, "received", "Yes");
			if (!row.date) frappe.model.set_value(cdt, cdn, "date", frappe.datetime.get_today());
		}
	},
	// Date is the day the document was received: today when Received is
	// set, cleared when it is unset (R2-15).
	received(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.received === "Yes") {
			if (!row.date) frappe.model.set_value(cdt, cdn, "date", frappe.datetime.get_today());
		} else if (row.date) {
			frappe.model.set_value(cdt, cdn, "date", null);
		}
	},
});

// ---------------------------------------------------------------------------
// ATD / ATA record what has happened: neither can be after today (R2-19).
// The server refuses one too (Operations.validate_actual_dates).
// ---------------------------------------------------------------------------

const ACTUAL_DATE_FIELDS = ["atd_date", "ata_date"];

// The last accepted value of each actual date, to go back to when a new one
// is refused (R3-22).
function remember_actual_dates(frm) {
	frm._accepted_actuals = {};
	ACTUAL_DATE_FIELDS.forEach((f) => (frm._accepted_actuals[f] = frm.doc[f] || null));
}

// Mark the field red, or clear the mark. The desk has $wrapper; the Vue
// app's form shim may not, so both are optional.
function mark_field_error(frm, fieldname, on) {
	const field = frm.fields_dict && frm.fields_dict[fieldname];
	const $wrapper = field && field.$wrapper;
	if ($wrapper && $wrapper.toggleClass) $wrapper.toggleClass("has-error", !!on);
	if (frm.set_df_property) frm.set_df_property(fieldname, "invalid", on ? 1 : 0);
}

function refuse_future_actual(frm, fieldname, label) {
	const value = frm.doc[fieldname];
	const today = frappe.datetime.get_today();
	if (!frm._accepted_actuals) remember_actual_dates(frm);
	if (frm._restoring_actual === fieldname) return; // our own put-back below
	if (!value || String(value).slice(0, 10) <= today) {
		frm._accepted_actuals[fieldname] = value || null;
		mark_field_error(frm, fieldname, false);
		return;
	}
	// Back to what it was before (or empty), and red until it is fixed.
	const previous = frm._accepted_actuals[fieldname] || null;
	frm._restoring_actual = fieldname;
	Promise.resolve(frm.set_value(fieldname, previous)).finally(() => {
		frm._restoring_actual = null;
		mark_field_error(frm, fieldname, true);
	});
	frappe.msgprint({
		title: __("Date in the future"),
		message: __("{0} cannot be after today ({1}): it records what has already happened.", [
			label,
			frappe.datetime.str_to_user ? frappe.datetime.str_to_user(today) : today,
		]),
		indicator: "red",
	});
}

// Picking a customer fills Salesman with the customer's Default Salesperson
// (M-04); the user can still change it. A customer with none leaves it alone.
async function fill_salesman_from_customer(frm) {
	const customer = frm.doc.customer;
	if (!customer || cint(frm.doc.docstatus) > 0) return;
	const r = await frappe.call({
		method: "forwarding.api.customer_360.default_salesperson",
		args: { customer },
	});
	const salesman = r && r.message;
	if (salesman && frm.doc.customer === customer && frm.doc.salesman !== salesman) {
		frm.set_value("salesman", salesman);
	}
}

frappe.ui.form.on("Operations", {
	refresh: remember_actual_dates,
	atd_date: (frm) => refuse_future_actual(frm, "atd_date", __("ATD")),
	ata_date: (frm) => refuse_future_actual(frm, "ata_date", __("ATA")),
	customer: fill_salesman_from_customer,
});

frappe.ui.form.on("Activity Template Table", {
	status(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.status === "Done" && !row.date) frappe.model.set_value(cdt, cdn, "date", frappe.datetime.get_today());
	},
});

frappe.ui.form.on("Cost Table", {
	cost(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "amount", flt(locals[cdt][cdn].cost));
	},
	// The item's default expense account for the job's company (R2-28); the
	// server fills it on save too, for rows added any other way.
	item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item) return;
		frappe.call({
			method: "forwarding.forwarding.doctype.operations.operations.default_expense_account",
			args: { item: row.item, company: frm.doc.company },
			callback: (r) => {
				if (r && r.message && locals[cdt][cdn] && locals[cdt][cdn].item === row.item) {
					frappe.model.set_value(cdt, cdn, "account", r.message);
				}
			},
		});
	},
});

// ---------------------------------------------------------------------------
// The Saudi side of a job (R3-05). An Import job arrives in Saudi Arabia, an
// Export job leaves from it: that side's country is filled and locked, and
// its port only lists Saudi ports. LAND TRANSPORT / Others are left free.
// The server applies the same (Operations.set_home_side).
// ---------------------------------------------------------------------------

const HOME_COUNTRY = "Saudi Arabia";
const HOME_SIDE = {
	Import: { country: "destination_country", port: "port_of_destination" },
	Export: { country: "loading_country", port: "port_of_loading" },
};

function home_side(frm) {
	return HOME_SIDE[frm.doc.job_type] || null;
}

// The Port.mode_of_shipment a job's mode lists (R3-24): seaports for Sea,
// airports for Air, land ports for Land; any for Others.
function port_mode(doc) {
	const mode = String(doc.mode_of_shipment || "").toLowerCase();
	if (mode.startsWith("sea")) return "Sea";
	if (mode === "air") return "Air";
	if (mode === "land") return "Land";
	return null;
}

function port_query(port_field) {
	return (doc) => {
		const filters = {};
		const side = HOME_SIDE[doc.job_type];
		if (side && side.port === port_field) filters.country = HOME_COUNTRY;
		const mode = port_mode(doc);
		if (mode) filters.mode_of_shipment = mode;
		return { filters };
	};
}

function apply_home_side(frm) {
	const side = home_side(frm);
	Object.values(HOME_SIDE).forEach(({ country }) => {
		frm.set_df_property(country, "read_only", side && side.country === country ? 1 : 0);
	});
	if (side && frm.doc.docstatus === 0 && frm.doc[side.country] !== HOME_COUNTRY) {
		frm.set_value(side.country, HOME_COUNTRY);
	}
}

frappe.ui.form.on("Operations", {
	setup(frm) {
		frm.set_query("port_of_destination", port_query("port_of_destination"));
		frm.set_query("port_of_loading", port_query("port_of_loading"));
	},
	refresh(frm) {
		// set_query again: the Vue app's form shim may not run setup.
		frm.set_query("port_of_destination", port_query("port_of_destination"));
		frm.set_query("port_of_loading", port_query("port_of_loading"));
		apply_home_side(frm);
	},
	job_type: apply_home_side,
	// The ports fetch their country into these fields; put the home side back.
	port_of_destination: apply_home_side,
	port_of_loading: apply_home_side,
});

// Company is shown only when the site has more than one (R3-33).
frappe.ui.form.on("Operations", {
	async refresh(frm) {
		if (frm._company_count === undefined) {
			try {
				frm._company_count = await frappe.db.count("Company");
			} catch (e) {
				frm._company_count = 2;
			}
		}
		frm.toggle_display("company", frm._company_count > 1 || !frm.doc.company);
	},
});

// Weight UOM offers weight units only (R3-31), as Operations.WEIGHT_UOMS.
const WEIGHT_UOMS = ["Kg", "Tonne", "Pound"];
frappe.ui.form.on("Operations", {
	setup(frm) {
		frm.set_query("weight_uom", () => ({ filters: { name: ["in", WEIGHT_UOMS] } }));
	},
	refresh(frm) {
		frm.set_query("weight_uom", () => ({ filters: { name: ["in", WEIGHT_UOMS] } }));
	},
});

// Services fill in from Job Type + Mode + Scope of Work (R3-23): the codes
// each scope's core service types call for (forwarding.services.
// default_services). Services the user added that still fit are kept; ones
// that no longer fit the new type / mode / scope are dropped.
async function fill_default_services(frm) {
	if (cint(frm.doc.docstatus) > 0 || !frm.doc.job_type || !frm.doc.mode_of_shipment) return;
	const scopes = scope_names(frm.doc);
	if (!scopes.length) return;
	const asked = [frm.doc.job_type, frm.doc.mode_of_shipment, JSON.stringify(scopes)].join("|");
	frm._services_for = asked;
	const r = await frappe.call({
		method: "forwarding.services.default_services",
		args: { job_type: frm.doc.job_type, mode_of_shipment: frm.doc.mode_of_shipment, scopes_of_work: JSON.stringify(scopes) },
	});
	if (frm._services_for !== asked) return; // a later change is on its way
	const defaults = (r && r.message) || [];
	const current = (frm.doc.services || []).map((row) => row.activity_code).filter(Boolean);
	let keep = [];
	if (current.length) {
		const q = await frappe.call({
			method: "forwarding.services.activity_code_query",
			args: { doctype: "Freight Activity Code", txt: "", searchfield: "name", start: 0, page_len: 500,
				filters: services_query(Object.assign({}, frm.doc, { services: [] })).filters },
		});
		const fitting = new Set(((q && q.message) || []).map((row) => row[0]));
		keep = current.filter((code) => fitting.has(code) && !defaults.includes(code));
	}
	const next = [...defaults, ...keep];
	if (next.join("|") === current.join("|")) return;
	frm.set_value("services", next.map((activity_code) => ({ activity_code })));
}

frappe.ui.form.on("Operations", {
	job_type: fill_default_services,
	mode_of_shipment: fill_default_services,
	scopes_of_work: fill_default_services,
});

// Each field narrows the next (R3-24); forwarding.job_rules applies the same
// on save. LAND TRANSPORT fixes the mode to Land; Land has no Port to Port
// scope; the estimate's items leave out what the job type / mode cannot carry.
const MODE_FOR_JOB_TYPE = { "LAND TRANSPORT": "Land" };
const SCOPES_NOT_FOR_MODE = { Land: ["Port to Port"] };

function scope_query(doc) {
	const excluded = SCOPES_NOT_FOR_MODE[port_mode(doc)] || [];
	return excluded.length ? { filters: { name: ["not in", excluded] } } : {};
}

function estimate_item_query(doc) {
	return {
		query: "forwarding.job_rules.estimate_item_query",
		filters: { job_type: doc.job_type || "", mode_of_shipment: doc.mode_of_shipment || "" },
	};
}

function apply_job_type_mode(frm) {
	const forced = MODE_FOR_JOB_TYPE[frm.doc.job_type];
	frm.set_df_property("mode_of_shipment", "read_only", forced ? 1 : 0);
	if (forced && frm.doc.mode_of_shipment !== forced && cint(frm.doc.docstatus) === 0) {
		frm.set_value("mode_of_shipment", forced);
	}
}

function set_narrowing_queries(frm) {
	frm.set_query("scopes_of_work", scope_query);
	frm.set_query("scope_of_work", "scopes_of_work", scope_query);
	frm.set_query("item", "cost_table", estimate_item_query);
}

frappe.ui.form.on("Operations", {
	setup: set_narrowing_queries,
	refresh(frm) {
		set_narrowing_queries(frm);
		apply_job_type_mode(frm);
	},
	job_type: apply_job_type_mode,
});
