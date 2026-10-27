// Create → Credit Note on a submitted Sales Invoice (Addendum A-11): a return
// invoice against it for the full or a partial amount, with the reason ZATCA
// needs. forwarding.credit_note makes the draft; it is reviewed and submitted
// from its own form.
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

	frappe.ui.form.on("Sales Invoice", {
		refresh(frm) {
			if (frm.doc.docstatus === 1 && !frm.doc.is_return) {
				frm.add_custom_button(__("Credit Note"), () => credit_note_dialog(frm), __("Create"));
			}
		},
	});
})();
