// A bill's job (Purchase Invoice, Sales Invoice) decides its Project, Branch
// and Cost Center, on the bill and every item row (A-02); they are read-only
// while a job is set. With no job the Project is cleared (A-03). Only a
// submitted job that is still open can be billed (A-04). The server applies
// the same in forwarding.purchase_invoice.fill_from_job.
// Wrapped: the desk evaluates doctype JS at global scope, once per DocType.
(() => {
	const JOB_BILL_FIELDS = ["project", "branch", "cost_center"];

	function job_bill_query(frm) {
		frm.set_query("operations", () => ({
			filters: [
				["Operations", "docstatus", "=", 1],
				["Operations", "operations_status", "not in", ["Closed", "Cancelled"]],
			],
		}));
	}

	function job_bill_lock(frm) {
		const locked = frm.doc.operations ? 1 : 0;
		for (const field of JOB_BILL_FIELDS) {
			if (frm.fields_dict[field]) frm.set_df_property(field, "read_only", locked);
		}
		// A saved bill stays with its job (A-14); a new one picks it.
		if (frm.fields_dict.operations) frm.set_df_property("operations", "read_only", !frm.is_new() && locked ? 1 : 0);
	}

	async function job_bill_values(job) {
		if (!job) return { project: "" };
		const r = await frappe.db.get_value("Operations", job, JOB_BILL_FIELDS);
		const values = (r && r.message !== undefined ? r.message : r) || {};
		return { project: values.project || job, branch: values.branch, cost_center: values.cost_center };
	}

	async function job_bill_apply(frm) {
		const job = frm.doc.operations;
		const values = await job_bill_values(job);
		if (frm.doc.operations !== job) return;
		for (const [field, value] of Object.entries(values)) {
			if (value === undefined || value === null) continue;
			if (frm.fields_dict[field] && frm.doc[field] !== value) await frm.set_value(field, value);
			for (const row of frm.doc.items || []) row[field] = value;
		}
		frm.refresh_field("items");
		job_bill_lock(frm);
	}

	// Loaded with each invoice DocType; register both once.
	if (frappe.flags.job_bill_registered) return;
	frappe.flags.job_bill_registered = true;

	for (const doctype of ["Purchase Invoice", "Sales Invoice"]) {
		frappe.ui.form.on(doctype, {
			setup: job_bill_query,
			onload: job_bill_query,
			refresh(frm) {
				job_bill_lock(frm);
				// A new bill with no job carries no leftover job Project (A-03).
				if (frm.is_new() && !frm.doc.operations && frm.doc.project) frm.set_value("project", "");
			},
			operations: job_bill_apply,
		});
		frappe.ui.form.on(`${doctype} Item`, {
			items_add(frm, cdt, cdn) {
				const row = locals[cdt][cdn];
				if (!frm.doc.operations) return;
				for (const field of JOB_BILL_FIELDS) {
					if (frm.doc[field]) row[field] = frm.doc[field];
				}
				frm.refresh_field("items");
			},
		});
	}
})();
