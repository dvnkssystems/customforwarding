frappe.pages['ship-supply-status'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Ship Supply — Delivery Status'),
		single_column: true,
	});

	// Desk-header controls (visible only when NOT in full-screen kiosk mode).
	page.set_primary_action(__('Full Screen'), () => enter_fullscreen(), 'expand');
	page.set_secondary_action(__('Refresh'), () => render(), 'refresh');
	page.add_inner_button(__('New Order'), () => frappe.new_doc('Ship Supply Order'));

	// Kiosk full-screen: hide the desk navbar + page head so the board
	// fills the viewport. Cleaned up automatically when leaving the page.
	function enter_fullscreen() { document.body.classList.add('sss-fullscreen'); }
	function exit_fullscreen() { document.body.classList.remove('sss-fullscreen'); }
	frappe.pages['ship-supply-status'].on_page_show = enter_fullscreen;
	frappe.router.on('change', () => {
		if ((frappe.get_route() || [])[0] !== 'ship-supply-status') exit_fullscreen();
	});

	inject_styles();

	const FA = {
		clipboard: 'fa-clipboard-list', box: 'fa-box', forklift: 'fa-dolly',
		'truck-clock': 'fa-truck', truck: 'fa-truck-moving', loader: 'fa-truck-ramp-box',
		'truck-fast': 'fa-truck-fast', check: 'fa-circle-check', return: 'fa-rotate-left',
		'clipboard-check': 'fa-clipboard-check',
	};

	const $board = $('<div class="sss-board"></div>').appendTo(page.body);
	const esc = frappe.utils.escape_html;

	function render() {
		frappe.call({ method: 'forwarding.api.get_ship_supply_board' }).then((r) => {
			const d = r.message || {};
			const counters = d.counters || [];
			const orders = d.orders || [];
			const statuses = d.statuses || [];
			const colorOf = {};
			statuses.forEach((s) => { colorOf[s.label] = s.color; });
			const ps = d.pallet_summary || {};
			const rs = d.return_summary || {};

			let html = '';

			// Header
			html += `<div class="sss-hdr">
				<div class="sss-title">SHIP SUPPLY — DELIVERY STATUS</div>
				<div class="sss-hdr-right">
					<div class="sss-actions">
						<button class="sss-btn" data-act="new"><i class="fa-solid fa-plus"></i> New Order</button>
						<button class="sss-btn" data-act="refresh"><i class="fa-solid fa-rotate"></i></button>
						<button class="sss-btn sss-exit" data-act="exit"><i class="fa-solid fa-compress"></i> Exit</button>
					</div>
					<div class="sss-clock"><div class="sss-time" id="sss-time">--:--</div>
					<div class="sss-date" id="sss-date"></div></div>
				</div></div>`;

			// Counter cards
			html += `<div class="sss-counters">`;
			counters.forEach((c) => {
				html += `<div class="sss-counter" style="background:linear-gradient(160deg, ${c.color}, rgba(0,0,0,.35));">
					<div class="sss-c-top"><i class="fa-solid ${FA[c.icon] || 'fa-circle'}"></i>
					<span class="sss-lbl">${esc(c.label)}</span></div>
					<div class="sss-val">${c.value}</div></div>`;
			});
			html += `</div>`;

			// Orders table
			html += `<div class="sss-grid"><table><thead><tr>
				<th style="width:9%">Order No.</th><th style="width:11%">Ship Name</th>
				<th style="width:8%">Catering Group</th><th style="width:9%">Supervisor</th>
				<th style="width:9%">Pallet No.</th><th style="width:6%">Pallets</th>
				<th style="width:13%">Status</th><th style="width:8%">Vehicle No.</th>
				<th style="width:7%">Driver</th><th style="width:7%">Ready Time</th>
				<th style="width:7%">ETA / Delivery</th><th style="width:10%">Remarks</th>
				</tr></thead><tbody>`;
			if (!orders.length) {
				html += `<tr><td colspan="12" style="padding:28px;color:var(--sss-muted)">
					${__('No orders for today.')} <a href="#" class="sss-new">${__('Create one')}</a>.</td></tr>`;
			}
			orders.forEach((o) => {
				const col = colorOf[o.status] || '#5b6470';
				html += `<tr>
					<td class="sss-order" style="color:${col}"><a href="/app/ship-supply-order/${encodeURIComponent(o.order_no)}" style="color:${col}">${esc(o.order_no)}</a></td>
					<td>${esc(o.ship)}</td><td>${esc(o.group)}</td><td>${esc(o.supervisor)}</td>
					<td>${esc(o.pallet_range)}</td><td>${o.pallets}</td>
					<td><span class="sss-badge" style="background:${col}">${esc(o.status)}</span></td>
					<td>${esc(o.vehicle)}</td><td>${esc(o.driver)}</td>
					<td>${esc(o.ready_time)}</td><td>${esc(o.eta)}</td>
					<td class="sss-remark">${esc(o.remarks)}</td></tr>`;
			});
			html += `</tbody></table></div>`;

			// Bottom panels
			html += `<div class="sss-bottom">`;
			html += `<div class="sss-panel"><div class="sss-p-head sss-blue">STATUS LEGEND</div>
				<div class="sss-p-body"><div class="sss-legend">`;
			statuses.forEach((s) => {
				html += `<div class="sss-leg"><span class="sss-dot" style="background:${s.color}"></span>${esc(s.label)}</div>`;
			});
			html += `</div></div></div>`;

			html += `<div class="sss-panel"><div class="sss-p-head sss-blue">PALLET SUMMARY</div>
				<div class="sss-p-body"><div class="sss-summary">
				<div class="sss-cell"><i class="fa-solid fa-pallet"></i><div class="sss-s-lbl">TOTAL PALLETS</div><div class="sss-s-val">${ps.total || 0}</div></div>
				<div class="sss-cell"><i class="fa-solid fa-truck-fast"></i><div class="sss-s-lbl">DISPATCHED</div><div class="sss-s-val">${ps.dispatched || 0}</div></div>
				<div class="sss-cell"><i class="fa-solid fa-boxes-stacked"></i><div class="sss-s-lbl">REMAINING</div><div class="sss-s-val">${ps.remaining || 0}</div></div>
				</div></div></div>`;

			html += `<div class="sss-panel"><div class="sss-p-head sss-red">RETURN SUMMARY</div>
				<div class="sss-p-body"><div class="sss-summary sss-ret">
				<div class="sss-cell"><i class="fa-solid fa-rotate-left"></i><div class="sss-s-lbl">RETURNED TODAY</div><div class="sss-s-val">${rs.returned_today || 0}</div></div>
				<div class="sss-cell"><i class="fa-solid fa-clipboard-list"></i><div class="sss-s-lbl">PENDING ACTION</div><div class="sss-s-val">${rs.pending_action || 0}</div></div>
				<div class="sss-cell"><i class="fa-solid fa-circle-check sss-ok"></i><div class="sss-s-lbl">CLOSED</div><div class="sss-s-val">${rs.closed || 0}</div></div>
				</div></div></div>`;
			html += `</div>`;

			// Footer
			html += `<div class="sss-footer">
				<i class="fa-solid fa-triangle-exclamation sss-warn"></i>
				<span>** SAFETY FIRST</span><span class="sss-sep">|</span>
				<span>QUALITY ALWAYS</span><span class="sss-sep">|</span>
				<span>ON TIME EVERY TIME **</span><i class="fa-solid fa-ship sss-ship"></i></div>`;

			$board.html(html);
			$board.find('.sss-new').on('click', (e) => { e.preventDefault(); frappe.new_doc('Ship Supply Order'); });
			$board.find('[data-act="new"]').on('click', () => frappe.new_doc('Ship Supply Order'));
			$board.find('[data-act="refresh"]').on('click', () => render());
			$board.find('[data-act="exit"]').on('click', () => exit_fullscreen());
			tick();
		});
	}

	function tick() {
		const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
		const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
		const pad = (n) => (n < 10 ? '0' + n : '' + n);
		const dt = new Date();
		let h = dt.getHours();
		const ap = h >= 12 ? 'PM' : 'AM';
		h = h % 12 || 12;
		const $t = $board.find('#sss-time'), $d = $board.find('#sss-date');
		if ($t.length) $t.text(`${h}:${pad(dt.getMinutes())} ${ap}`);
		if ($d.length) $d.text(`${days[dt.getDay()]}, ${pad(dt.getDate())} ${months[dt.getMonth()]} ${dt.getFullYear()}`);
	}

	render();
	// Live clock + periodic data refresh; cleared when leaving the page.
	const clockTimer = setInterval(tick, 30 * 1000);
	const dataTimer = setInterval(render, 60 * 1000);
	$(wrapper).on('remove', () => { clearInterval(clockTimer); clearInterval(dataTimer); });
};

function inject_styles() {
	if (!document.getElementById('sss-fa')) {
		const l = document.createElement('link');
		l.id = 'sss-fa';
		l.rel = 'stylesheet';
		l.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css';
		document.head.appendChild(l);
	}
	if (document.getElementById('sss-style')) return;
	const s = document.createElement('style');
	s.id = 'sss-style';
	s.textContent = `
	.sss-board { --sss-bg:#05070d; --sss-border:#16305c; --sss-head:#10305e; --sss-txt:#e8eefc; --sss-muted:#9fb0cc;
		background:var(--sss-bg); color:var(--sss-txt); border-radius:12px; padding:14px 16px; margin:-1px;
		font-family:"Segoe UI",Roboto,Arial,sans-serif; }
	.sss-board * { box-sizing:border-box; }
	.sss-hdr { display:flex; align-items:center; justify-content:space-between; padding:4px 6px 12px; }
	.sss-title { font-size:26px; font-weight:800; letter-spacing:4px; color:#d9a521; text-shadow:0 0 12px rgba(217,165,33,.25); }
	.sss-hdr-right { display:flex; align-items:center; gap:18px; }
	.sss-actions { display:flex; gap:8px; }
	.sss-btn { background:rgba(255,255,255,.08); color:#e8eefc; border:1px solid #16305c; border-radius:8px;
		padding:8px 12px; font-size:13px; font-weight:700; cursor:pointer; }
	.sss-btn:hover { background:rgba(255,255,255,.16); }
	.sss-btn.sss-exit { color:#d9a521; border-color:#5a4a12; }
	.sss-clock { text-align:right; line-height:1; }
	.sss-time { font-size:30px; font-weight:800; color:#d9a521; }
	.sss-date { font-size:13px; font-weight:700; color:var(--sss-muted); letter-spacing:2px; margin-top:4px; }
	.sss-counters { display:grid; grid-template-columns:repeat(10,1fr); gap:10px; margin-bottom:14px; }
	.sss-counter { border-radius:10px; padding:10px 8px 8px; border:1px solid rgba(255,255,255,.08); min-height:110px;
		display:flex; flex-direction:column; justify-content:space-between; }
	.sss-c-top { display:flex; align-items:center; gap:8px; }
	.sss-c-top i { font-size:17px; opacity:.9; }
	.sss-lbl { font-size:11px; font-weight:700; line-height:1.15; text-transform:uppercase; }
	.sss-val { font-size:36px; font-weight:800; }
	.sss-grid { border:1px solid var(--sss-border); border-radius:10px; overflow:hidden; }
	.sss-board table { width:100%; border-collapse:collapse; table-layout:fixed; margin:0; }
	.sss-board thead th { background:var(--sss-head); color:var(--sss-txt); font-size:12px; font-weight:700;
		padding:11px 8px; text-transform:uppercase; border-right:1px solid var(--sss-border); text-align:center; }
	.sss-board tbody td { padding:11px 8px; text-align:center; font-size:13px; font-weight:600; color:var(--sss-txt);
		border-right:1px solid rgba(255,255,255,.05); border-top:1px solid rgba(255,255,255,.05); }
	.sss-board tbody tr:nth-child(odd) { background:#04060c; }
	.sss-board tbody tr:nth-child(even) { background:#070c16; }
	.sss-order { font-weight:700; }
	.sss-remark { font-weight:500; color:var(--sss-muted); }
	.sss-badge { display:inline-block; min-width:140px; padding:8px 10px; border-radius:6px; color:#fff;
		font-weight:700; font-size:12px; text-transform:uppercase; }
	.sss-bottom { display:grid; grid-template-columns:1.6fr 1fr 1fr; gap:14px; margin:14px 0; }
	.sss-panel { border:1px solid var(--sss-border); border-radius:10px; overflow:hidden; background:#04060c; }
	.sss-p-head { padding:8px; text-align:center; font-weight:800; letter-spacing:2px; font-size:15px; }
	.sss-blue { background:#10305e; } .sss-red { background:#5a1414; }
	.sss-p-body { padding:14px 16px; }
	.sss-legend { display:grid; grid-template-columns:repeat(3,1fr); gap:8px 18px; }
	.sss-leg { display:flex; align-items:center; gap:8px; font-size:12px; font-weight:600; color:#d6def0; }
	.sss-dot { width:12px; height:12px; border-radius:50%; flex:0 0 auto; }
	.sss-summary { display:flex; justify-content:space-around; text-align:center; }
	.sss-cell i { font-size:28px; color:#2f8fed; }
	.sss-ret .sss-cell i { color:#d63030; }
	.sss-ret .sss-cell .sss-ok { color:#2fa32f; }
	.sss-s-lbl { font-size:12px; font-weight:700; color:var(--sss-muted); margin:8px 0 4px; }
	.sss-s-val { font-size:30px; font-weight:800; }
	.sss-footer { border-top:2px solid #16305c; background:#071227; border-radius:0 0 8px 8px; padding:12px;
		text-align:center; color:#d9a521; font-weight:800; font-size:18px; letter-spacing:2px;
		display:flex; align-items:center; justify-content:center; gap:24px; }
	.sss-sep { color:#16305c; } .sss-warn { color:#d9a521; } .sss-ship { color:#6f8bbf; }
	@media (max-width:1200px){ .sss-counters{grid-template-columns:repeat(5,1fr);} .sss-bottom{grid-template-columns:1fr;} .sss-legend{grid-template-columns:repeat(2,1fr);} }

	/* Full-screen kiosk mode: board fills the viewport, desk chrome hidden. */
	body.sss-fullscreen .navbar,
	body.sss-fullscreen .page-head { display:none !important; }
	body.sss-fullscreen { overflow:hidden; }
	body.sss-fullscreen .sss-board { position:fixed; inset:0; z-index:1040; margin:0;
		border-radius:0; overflow:auto; padding:16px 20px; }
	`;
	document.head.appendChild(s);
}
