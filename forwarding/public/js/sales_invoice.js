// Create → Credit Note on a submitted Sales Invoice (Addendum A-11): a return
// invoice against it for the full or a partial amount, with the reason ZATCA
// needs. forwarding.credit_note makes the draft; it is reviewed and submitted
// from its own form. Record Payment while it is owed (A-12).
// Wrapped: the desk evaluates doctype JS at global scope, once per DocType.
(() => {
	// The desk's format_currency; the app has none, so plain figures there.
	const money = (value, currency) =>
		typeof format_currency === "function" ? format_currency(value, currency) : `${currency} ${flt(value).toFixed(2)}`;

	function credit_note_dialog(frm) {
		const total = flt(frm.doc.grand_total);
		const dialog = new frappe.ui.Dialog({
			title: __("Credit Note for {0}", [frm.doc.name]),
			// Two fields only: the app's dialog has no depends_on or descriptions,
			// so the label carries the hint.
			fields: [
				{
					fieldname: "amount",
					fieldtype: "Currency",
					label: __("Amount to credit, incl. VAT (empty: the full {0})", [money(total, frm.doc.currency)]),
				},
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason (printed on the credit note)"),
					reqd: 1,
				},
			],
			primary_action_label: __("Create Credit Note"),
			async primary_action(values) {
				const amount = flt(values.amount);
				const partial = amount > 0 && amount < total;
				if (amount < 0 || amount > total) {
					frappe.msgprint(__("Enter an amount up to {0}.", [money(total, frm.doc.currency)]));
					return;
				}
				let r;
				try {
					r = await frappe.call({
						method: "forwarding.credit_note.make_credit_note",
						args: { source_name: frm.doc.name, reason: values.reason, amount: partial ? amount : null },
						freeze: true,
					});
				} catch (e) {
					// The desk has already shown the server's message; the app throws an Error.
					if (e instanceof Error) frappe.msgprint(e.message);
					return;
				}
				dialog.hide();
				if (r && r.message) frappe.set_route("Form", "Sales Invoice", r.message);
			},
		});
		dialog.show();
	}

	// VAT per line (ONE Freight, 12 Nov): the line's VAT choice and its Item
	// Tax Template follow each other. forwarding.line_vat does the same on
	// save; here the form (desk and app) shows the new VAT at once.
	const vat_options = {};
	async function vat_map(company) {
		if (!company) return [];
		if (!vat_options[company]) {
			vat_options[company] = frappe
				.call("forwarding.line_vat.options", { company })
				.then((r) => (r && r.message !== undefined ? r.message : r) || [])
				.catch(() => {
					delete vat_options[company];
					return [];
				});
		}
		return vat_options[company];
	}

	frappe.ui.form.on("Sales Invoice Item", {
		async vat_type(frm, cdt, cdn) {
			const row = locals[cdt] && locals[cdt][cdn] ? locals[cdt][cdn] : (frm.doc.items || []).find((r) => r.name === cdn);
			if (!row || !row.vat_type || frm.doc.docstatus !== 0) return;
			const option = (await vat_map(frm.doc.company)).find((o) => o.vat_type === row.vat_type);
			if (!option || row.item_tax_template === option.template) return;
			await frappe.model.set_value(cdt, cdn, {
				item_tax_template: option.template,
				item_tax_rate: JSON.stringify(option.item_tax_rate || {}),
			});
		},
		async item_tax_template(frm, cdt, cdn) {
			const row = locals[cdt] && locals[cdt][cdn] ? locals[cdt][cdn] : (frm.doc.items || []).find((r) => r.name === cdn);
			if (!row || !row.item_tax_template || frm.doc.docstatus !== 0) return;
			const option = (await vat_map(frm.doc.company)).find((o) => o.template === row.item_tax_template);
			if (option && row.vat_type !== option.vat_type) {
				await frappe.model.set_value(cdt, cdn, { vat_type: option.vat_type });
			}
		},
	});

	frappe.ui.form.on("Sales Invoice", {
		refresh(frm) {
			if (frm.doc.docstatus === 1 && !frm.doc.is_return) {
				frm.add_custom_button(__("Credit Note"), () => credit_note_dialog(frm), __("Create"));
			}
			// Record Payment while anything is outstanding (A-12): ERPNext's own
			// Payment Entry for the balance, opened unsaved.
			if (frm.doc.docstatus === 1 && !frm.doc.is_return && flt(frm.doc.outstanding_amount) > 0) {
				frm.add_custom_button(__("Record Payment"), () =>
					frappe.model.open_mapped_doc({ method: "forwarding.sales_invoice.make_payment", frm })
				);
			}
		},
	});
})();
