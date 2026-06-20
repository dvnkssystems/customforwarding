frappe.pages['finance-dashboard'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Finance Dashboard'),
		single_column: true,
	});
	const $body = $(`<div class="finance-dashboard" style="padding:12px;"></div>`).appendTo(page.body);

	function card(label, val, colour) {
		return `<div style="flex:1;min-width:180px;border:1px solid var(--border-color);border-radius:10px;padding:14px;">
			<div style="font-size:12px;color:var(--text-muted);">${frappe.utils.escape_html(label)}</div>
			<div style="font-size:24px;font-weight:700;color:${colour || 'var(--text-color)'};">${val}</div></div>`;
	}

	frappe.call({ method: 'forwarding.api.get_finance_stats' }).then((r) => {
		const d = r.message || {};
		const fmt = (v) => format_currency(v || 0);
		const margin = (d.revenue || 0) - (d.cost || 0);
		$body.html(`<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
			${card(__('Accounts Receivable'), fmt(d.receivable), '#cb7c00')}
			${card(__('Accounts Payable'), fmt(d.payable), '#c0392b')}
			${card(__('Revenue'), fmt(d.revenue), '#2e7d32')}
			${card(__('Cost'), fmt(d.cost), '#6c7680')}
			${card(__('Margin'), fmt(margin), margin >= 0 ? '#2e7d32' : '#c0392b')}
		</div>`);
	});
};
