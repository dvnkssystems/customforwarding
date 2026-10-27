// A bill's supplier fills its currency, exchange rate, payable account and
// buying price list (A-07, A-08). The desk gets these from ERPNext's buying
// controller on the supplier's change; the app's form does not load that
// controller, so a bill opened from the supplier page had no currency
// ("Exchange Rate is mandatory… None to SAR"). Only empty fields are filled,
// so on the desk this follows ERPNext's own handler rather than fighting it.
// Wrapped: the desk evaluates doctype JS at global scope, once per DocType.
(() => {
	async function bill_party_details(frm) {
		const doc = frm.doc;
		if (!doc.supplier || !doc.company || doc.docstatus) return;
		const r = await frappe.call({
			method: "erpnext.accounts.party.get_party_details",
			args: {
				party: doc.supplier,
				party_type: "Supplier",
				company: doc.company,
				posting_date: doc.posting_date,
				bill_date: doc.bill_date,
				currency: doc.currency,
				price_list: doc.buying_price_list,
				doctype: doc.doctype,
			},
		});
		const details = (r && r.message) || {};
		if (frm.doc.supplier !== doc.supplier) return;

		for (const field of ["currency", "credit_to", "buying_price_list", "supplier_name"]) {
			if (details[field] && !frm.doc[field]) await frm.set_value(field, details[field]);
		}
		await bill_exchange_rate(frm);
	}

	async function bill_exchange_rate(frm) {
		const currency = frm.doc.currency;
		if (!currency || !frm.doc.company) return;
		const r0 = await frappe.db.get_value("Company", frm.doc.company, "default_currency");
		const base = ((r0 && r0.message !== undefined ? r0.message : r0) || {}).default_currency;
		if (!base) return;
		if (currency === base) {
			if (flt(frm.doc.conversion_rate) !== 1) await frm.set_value("conversion_rate", 1);
			return;
		}
		if (flt(frm.doc.conversion_rate) && flt(frm.doc.conversion_rate) !== 1) return;
		const r = await frappe.call({
			method: "erpnext.setup.utils.get_exchange_rate",
			args: { from_currency: currency, to_currency: base, transaction_date: frm.doc.posting_date },
		});
		if (r && r.message) await frm.set_value("conversion_rate", r.message);
	}

	frappe.ui.form.on("Purchase Invoice", {
		refresh(frm) {
			if (frm.is_new() && frm.doc.supplier && !frm.doc.currency) bill_party_details(frm);
		},
		supplier: bill_party_details,
		currency: bill_exchange_rate,
	});
})();
