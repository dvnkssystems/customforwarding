// A payment's bank or cash account follows its Mode of Payment (A-20): "Cash
// Askar" pays from that cash account, not the bank left from before. The desk
// does this in ERPNext's payment_entry.js (erpnext.accounts.pos), which the
// app's form cannot run; this is the same lookup through the same method.
// Wrapped: the desk evaluates doctype JS at global scope, once per DocType.
(() => {
	async function payment_account_from_mode(frm) {
		const mode = frm.doc.mode_of_payment;
		if (!mode || !frm.doc.company || frm.doc.docstatus) return;
		let r;
		try {
			r = await frappe.call({
				method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.get_bank_cash_account",
				args: { mode_of_payment: mode, company: frm.doc.company },
			});
		} catch (e) {
			// No account on the mode: the server's message says which to set.
			if (e instanceof Error) frappe.msgprint(e.message);
			return;
		}
		const account = r && r.message && r.message.account;
		if (!account || frm.doc.mode_of_payment !== mode) return;
		const field = frm.doc.payment_type === "Receive" ? "paid_to" : "paid_from";
		if (frm.doc[field] !== account) await frm.set_value(field, account);
	}

	frappe.ui.form.on("Payment Entry", {
		mode_of_payment: payment_account_from_mode,
	});
})();
