frappe.pages['freight-dashboard'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Freight Dashboard'),
		single_column: true,
	});
	const $body = $(`<div class="freight-dashboard" style="padding:12px;"></div>`).appendTo(page.body);

	function card(label, val, colour) {
		return `<div style="flex:1;min-width:150px;border:1px solid var(--border-color);border-radius:10px;padding:14px;">
			<div style="font-size:12px;color:var(--text-muted);">${frappe.utils.escape_html(label)}</div>
			<div style="font-size:26px;font-weight:700;color:${colour || 'var(--text-color)'};">${val}</div></div>`;
	}

	frappe.call({ method: 'forwarding.api.get_dashboard_stats' }).then((r) => {
		const d = r.message || {};
		const b = d.billing || {};
		let html = `<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
			${card(__('Total Jobs'), d.total_jobs || 0)}
			${card(__('Open Jobs'), d.open_jobs || 0, '#cb7c00')}
			${card(__('Waybills'), d.waybills || 0, '#1f6fd6')}
			${card(__('Vouchers'), d.vouchers || 0, '#2e7d32')}
		</div>`;

		html += `<h5>${__('Billing Status')}</h5><div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
			${card(__('No Invoice'), b['No Invoice'] || 0, '#6c7680')}
			${card(__('Cost Sheet Pending'), b['Cost Sheet Pending'] || 0, '#cb7c00')}
			${card(__('Pending Billing'), b['Pending Billing'] || 0, '#1f6fd6')}
			${card(__('Billed'), b['Billed'] || 0, '#2e7d32')}
		</div>`;

		html += `<div style="display:flex;gap:24px;flex-wrap:wrap;">`;
		html += `<div style="flex:1;min-width:280px;"><h5>${__('Top 5 Customers')}</h5><table class="table table-bordered"><thead><tr><th>${__('Customer')}</th><th>${__('Jobs')}</th></tr></thead><tbody>`;
		(d.top_customers || []).forEach((c) => { html += `<tr><td>${frappe.utils.escape_html(c.customer || '')}</td><td>${c.cnt}</td></tr>`; });
		html += `</tbody></table></div>`;

		html += `<div style="flex:1;min-width:280px;"><h5>${__('Recent Jobs')}</h5><table class="table table-bordered"><thead><tr><th>${__('Job')}</th><th>${__('Customer')}</th><th>${__('Billing')}</th></tr></thead><tbody>`;
		(d.recent_jobs || []).forEach((j) => {
			html += `<tr><td><a href="/app/operations/${encodeURIComponent(j.name)}">${frappe.utils.escape_html(j.name)}</a></td><td>${frappe.utils.escape_html(j.customer || '')}</td><td>${frappe.utils.escape_html(j.billing_status || '')}</td></tr>`;
		});
		html += `</tbody></table></div></div>`;

		$body.html(html);
	});
};
