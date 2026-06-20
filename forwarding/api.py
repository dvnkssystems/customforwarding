# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Whitelisted API endpoints for forwarding (desk widgets + mobile)."""

import frappe


def seed_demo():
	"""Idempotent demo data for walkthrough screenshots. Not whitelisted."""
	frappe.flags.in_test = True  # skip subscription enforcement while seeding

	def ensure(doctype, filters, values):
		name = frappe.db.exists(doctype, filters)
		if name:
			return name
		d = frappe.get_doc(dict(doctype=doctype, **values))
		d.flags.ignore_mandatory = True
		d.flags.ignore_permissions = True
		d.insert(ignore_permissions=True)
		return d.name

	log = []
	if not frappe.db.exists("Territory", "Saudi Arabia"):
		t = frappe.get_doc({"doctype": "Territory", "territory_name": "Saudi Arabia",
			"is_group": 0, "is_country": 1, "abbreviation": "SA"})
		t.flags.ignore_mandatory = True
		t.insert(ignore_permissions=True)
	log.append("territory")

	br = ensure("Branch", {"branch": "Jeddah"}, {"branch": "Jeddah", "abbreviation": "JED"})
	jt = ensure("Job Type", {"job_type": "Import"}, {"job_type": "Import", "abbreviation": "IMP"})
	mos = ensure("Mode Of Shipment", {"mode_of_shipment": "Sea"}, {"mode_of_shipment": "Sea", "abbreviation": "SEA"})
	sow = ensure("Scope Of Work", {"scope_of_work": "Freight Forwarding"},
		{"scope_of_work": "Freight Forwarding", "abbreviation": "FF", "freight_forwarding": 1})

	for st in ["OPEN", "IN PROGRESS", "COMPLETED", "CLOSED"]:
		ensure("Operations Status", {"status": st}, {"status": st})

	ensure("Waybill Terms", {"title": "Standard Sea Terms"},
		{"title": "Standard Sea Terms", "language": "English", "is_default": 1,
		 "terms_content": "<p>Standard carriage terms apply.</p>"})
	ensure("Freight Airport", {"airport_name": "King Abdulaziz Intl"},
		{"airport_name": "King Abdulaziz Intl", "iata_code": "JED", "city": "Jeddah", "is_active": 1})
	ensure("Freight Seaport", {"port_name": "Jeddah Islamic Port"},
		{"port_name": "Jeddah Islamic Port", "un_locode": "SAJED", "city": "Jeddah", "is_active": 1})
	ensure("Freight Driver", {"driver_name": "Ahmed Ali"},
		{"driver_name": "Ahmed Ali", "mobile_no": "0500000000", "iqama_no": "2123456789"})
	ensure("Freight Truck", {"truck_no": "TRK-001"},
		{"truck_no": "TRK-001", "plate_no": "ABC-1234", "truck_type": "Trailer", "is_owned": 1})

	cg = (frappe.db.get_value("Customer Group", {"is_group": 0, "name": "Commercial"})
		or frappe.db.get_value("Customer Group", {"is_group": 0}))
	terr = (frappe.db.get_value("Territory", {"is_group": 0, "name": "Rest Of The World"})
		or frappe.db.get_value("Territory", {"is_group": 0}))
	cust = ensure("Customer", {"customer_name": "Acme Trading LLC"},
		{"customer_name": "Acme Trading LLC", "customer_type": "Company", "branch": br,
		 "customer_group": cg, "territory": terr,
		 "credit_period": "30 Days", "customer_rating": 4})

	job = frappe.db.get_value("Operations", {"customer": cust}, "name")
	if not job:
		j = frappe.get_doc({"doctype": "Operations", "country": "Saudi Arabia", "branch": br,
			"job_type": jt, "mode_of_shipment": mos, "scope_of_work": sow, "customer": cust,
			"date": frappe.utils.nowdate(), "awb_number": "BL-2026-0001",
			"net_weight": 12000, "gross_weight": 12500, "cargo_description": "General merchandise"})
		j.flags.ignore_mandatory = True
		j.insert(ignore_permissions=True)
		job = j.name
	log.append(f"customer={cust}")
	log.append(f"job={job}")
	frappe.db.commit()
	return " | ".join(log)


@frappe.whitelist()
def get_billing_status_counts():
	"""KPI counts of active (non-trashed) Operations grouped by billing_status."""
	rows = frappe.get_all(
		"Operations",
		filters={"is_trashed": 0},
		fields=["billing_status", "count(name) as cnt"],
		group_by="billing_status",
	)
	counts = {
		"No Invoice": 0,
		"Cost Sheet Pending": 0,
		"Pending Billing": 0,
		"Billed": 0,
	}
	for r in rows:
		counts[r.billing_status or "No Invoice"] = r.cnt
	return counts


@frappe.whitelist()
def get_dashboard_stats():
	"""Operation Dashboard KPIs."""
	billing = get_billing_status_counts()
	return {
		"total_jobs": frappe.db.count("Operations", {"is_trashed": 0}),
		"open_jobs": frappe.db.count("Operations", {"is_trashed": 0, "operations_status": "OPEN"}),
		"waybills": frappe.db.count("Freight Waybill", {"docstatus": ["<", 2]}),
		"vouchers": frappe.db.count("Freight Voucher", {"docstatus": 1}),
		"billing": billing,
		"top_customers": frappe.db.sql(
			"""select customer, count(name) as cnt from `tabOperations`
			   where is_trashed=0 and customer is not null
			   group by customer order by cnt desc limit 5""", as_dict=True),
		"recent_jobs": frappe.get_all("Operations", filters={"is_trashed": 0},
			fields=["name", "customer", "billing_status", "date"],
			order_by="creation desc", limit=10),
	}


@frappe.whitelist()
def get_finance_stats():
	"""Finance Dashboard KPIs."""
	def _sum(dt, field, filters):
		v = frappe.db.get_value(dt, filters, f"sum({field})")
		return v or 0
	return {
		"receivable": _sum("Sales Invoice", "outstanding_amount", {"docstatus": 1}),
		"payable": _sum("Purchase Invoice", "outstanding_amount", {"docstatus": 1}),
		"revenue": _sum("Sales Invoice", "base_grand_total", {"docstatus": 1}),
		"cost": _sum("Purchase Invoice", "base_grand_total", {"docstatus": 1}),
	}


# --------------------------------------------------------------------------
# Mobile API scaffolding (Module 15) — fleshed out in Phase 5.
# --------------------------------------------------------------------------
@frappe.whitelist()
def get_job_list(filters=None, page=1, page_size=20):
	filters = frappe.parse_json(filters) if filters else {}
	filters.setdefault("is_trashed", 0)
	page = int(page)
	page_size = int(page_size)
	return frappe.get_all(
		"Operations",
		filters=filters,
		fields=["name", "customer", "billing_status", "operations_status",
			"awb_number", "date", "mode_of_shipment"],
		start=(page - 1) * page_size,
		page_length=page_size,
		order_by="modified desc",
	)


@frappe.whitelist()
def get_job_detail(job_name):
	return frappe.get_doc("Operations", job_name).as_dict()


@frappe.whitelist()
def track_awb(awb_no):
	"""Return tracking events for an AWB/BL number."""
	name = frappe.db.get_value("Freight Tracking", {"tracking_ref": awb_no})
	if not name:
		return {"found": False, "events": []}
	doc = frappe.get_doc("Freight Tracking", name)
	return {
		"found": True,
		"tracking_ref": doc.tracking_ref,
		"last_status": doc.last_status,
		"events": [e.as_dict() for e in doc.tracking_events],
	}


@frappe.whitelist()
def update_job_status(job_name, status, remarks=None):
	"""Mobile/desk helper: push a status onto a job's Freight Job Status doc."""
	name = frappe.db.get_value("Freight Job Status", {"freight_job": job_name})
	if name:
		doc = frappe.get_doc("Freight Job Status", name)
	else:
		doc = frappe.new_doc("Freight Job Status")
		doc.freight_job = job_name
	doc.add_status(status)
	return doc.name


@frappe.whitelist(allow_guest=True)
def submit_job_request(payload):
	"""Guest endpoint backing the public Freight Job Request form."""
	data = frappe.parse_json(payload) if isinstance(payload, str) else payload
	allowed = {"partner_company", "partner_contact", "partner_email", "job_type",
		"awb_bl_no", "activity_code", "origin", "destination", "weight", "pieces",
		"cargo_description", "special_instructions"}
	doc = frappe.new_doc("Freight Job Request")
	for k, v in (data or {}).items():
		if k in allowed and v not in (None, ""):
			doc.set(k, v)
	doc.status = "Pending"
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def share_invoice(invoice_name):
	"""Generate (or return) a public token + link for a Sales Invoice."""
	import uuid
	doc = frappe.get_doc("Sales Invoice", invoice_name)
	if not doc.get("public_token"):
		doc.db_set("public_token", uuid.uuid4().hex)
	doc.db_set("is_public", 1)
	link = f"/invoice?token={doc.public_token}"
	doc.db_set("public_link", link)
	return {"public_link": link, "public_token": doc.public_token}


@frappe.whitelist()
def master_status_update(jobs, status_text, status_date=None, bayan_no=None):
	"""Bulk 'Master Status' update across many Freight Job Status records."""
	if isinstance(jobs, str):
		jobs = frappe.parse_json(jobs)
	updated = []
	for job in jobs:
		name = frappe.db.get_value("Freight Job Status", {"freight_job": job})
		if name:
			doc = frappe.get_doc("Freight Job Status", name)
		else:
			doc = frappe.new_doc("Freight Job Status")
			doc.freight_job = job
		if bayan_no:
			doc.bayan_no = bayan_no
		doc.add_status(status_text, status_date)
		updated.append(doc.name)
	frappe.db.commit()
	return {"updated": len(updated), "names": updated}


# --------------------------------------------------------------------------
# Generic CRUD + form metadata (backs the Forwarding SPA's in-app forms).
# Permissions are enforced normally (no ignore_permissions) so the desk role
# model applies. Child tables are handled via doc.update().
# --------------------------------------------------------------------------
_LAYOUT_FIELDTYPES = {"Column Break", "HTML", "Button", "Fold", "Heading", "Image"}
_SKIP_FIELDS = {"amended_from"}


def _form_fields(meta):
	out = []
	for f in meta.fields:
		# Tab/Section breaks are kept as markers so the UI can build real tabs.
		if f.fieldtype == "Tab Break":
			out.append({"fieldtype": "Tab Break", "label": f.label or ""})
			continue
		if f.fieldtype == "Section Break":
			out.append({"fieldtype": "Section Break", "label": f.label or ""})
			continue
		if f.fieldtype in _LAYOUT_FIELDTYPES:
			continue
		if f.hidden or f.fieldname in _SKIP_FIELDS:
			continue
		out.append({
			"fieldname": f.fieldname,
			"label": f.label,
			"fieldtype": f.fieldtype,
			"options": f.options,
			"reqd": int(f.reqd or 0),
			"default": f.default,
			"read_only": int(f.read_only or 0),
			"depends_on": f.depends_on,
			"precision": f.precision,
			"in_list_view": int(f.in_list_view or 0),
		})
	return out


@frappe.whitelist()
def form_meta(doctype):
	"""Simplified field metadata for rendering an in-app form, including the
	field lists of any child tables referenced by Table fields."""
	meta = frappe.get_meta(doctype)
	children = {}
	for f in meta.fields:
		if f.fieldtype == "Table" and f.options and f.options not in children:
			children[f.options] = _form_fields(frappe.get_meta(f.options))
	return {
		"doctype": doctype,
		"fields": _form_fields(meta),
		"children": children,
		"title_field": meta.title_field,
		"is_submittable": int(getattr(meta, "is_submittable", 0) or 0),
	}


@frappe.whitelist()
def doc_get(doctype, name):
	"""Full document as a dict (child tables included)."""
	return frappe.get_doc(doctype, name).as_dict()


@frappe.whitelist()
def doc_save(doctype, data, name=None):
	"""Insert (no name / not found) or update (existing name) a document.
	`data` is a JSON object; child tables are passed as arrays of row dicts."""
	data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	for k in ("doctype", "__islocal", "__unsaved", "owner", "creation",
		"modified", "modified_by", "idx", "docstatus"):
		data.pop(k, None)
	if name and frappe.db.exists(doctype, name):
		doc = frappe.get_doc(doctype, name)
		doc.update(data)
	else:
		doc = frappe.new_doc(doctype)
		doc.update(data)
	doc.save()
	frappe.db.commit()
	return {"name": doc.name, "doc": doc.as_dict()}


@frappe.whitelist()
def doc_submit(doctype, name):
	doc = frappe.get_doc(doctype, name)
	doc.submit()
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def doc_cancel(doctype, name):
	doc = frappe.get_doc(doctype, name)
	doc.cancel()
	frappe.db.commit()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def doc_delete(doctype, name):
	frappe.delete_doc(doctype, name)
	frappe.db.commit()
	return {"deleted": name}


# --------------------------------------------------------------------------
# Party addresses — Address links to a party (Customer/Supplier) through the
# `links` Dynamic Link child table, which the generic get_list can't filter on.
# --------------------------------------------------------------------------
@frappe.whitelist()
def get_party_addresses(party_type, party):
	"""All Addresses linked to a party, primary first."""
	names = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": party_type, "link_name": party},
		pluck="parent",
	)
	if not names:
		return []
	return frappe.get_all(
		"Address",
		filters={"name": ["in", names]},
		fields=[
			"name", "address_title", "address_type", "address_line1", "address_line2",
			"city", "state", "country", "pincode", "phone", "email_id",
			"is_primary_address", "is_shipping_address",
		],
		order_by="is_primary_address desc, modified desc",
	)


@frappe.whitelist()
def create_party_address(party_type, party, data):
	"""Insert an Address pre-linked to the given party."""
	data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	for k in ("doctype", "name", "links", "__islocal", "__unsaved"):
		data.pop(k, None)
	doc = frappe.new_doc("Address")
	doc.update(data)
	if not doc.address_title:
		doc.address_title = party
	doc.append("links", {"link_doctype": party_type, "link_name": party})
	doc.insert()
	frappe.db.commit()
	return {"name": doc.name, "doc": doc.as_dict()}


# --------------------------------------------------------------------------
# Rich demo data so every SPA report has something to show. Not whitelisted;
# run with:  bench --site <site> execute forwarding.api.seed_reports_demo
# Idempotent: guarded by the "FLCS-DEMO" remark marker on Sales Invoices.
# --------------------------------------------------------------------------
def seed_reports_demo():
	from frappe.utils import getdate, add_days, nowdate
	frappe.flags.in_test = True  # skip subscription enforcement
	log = []

	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		return "No Company found — create a company first."
	currency = frappe.db.get_value("Company", company, "default_currency") or "USD"
	cost_center = frappe.db.get_value("Company", company, "cost_center") \
		or frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
	income_acc = frappe.db.get_value("Account", {"company": company, "root_type": "Income", "is_group": 0}, "name")
	expense_acc = frappe.db.get_value("Account", {"company": company, "account_type": "Cost of Goods Sold", "is_group": 0}, "name") \
		or frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name")
	receivable = frappe.db.get_value("Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name")
	payable = frappe.db.get_value("Account", {"company": company, "account_type": "Payable", "root_type": "Liability", "is_group": 0}, "name")
	cash = frappe.db.get_value("Account", {"company": company, "account_type": ["in", ["Cash", "Bank"]], "is_group": 0}, "name")

	def ensure(doctype, filters, values):
		name = frappe.db.exists(doctype, filters)
		if name:
			return name
		d = frappe.get_doc(dict(doctype=doctype, **values))
		d.flags.ignore_mandatory = True
		d.flags.ignore_permissions = True
		d.insert(ignore_permissions=True)
		return d.name

	# --- masters ---
	cg = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	terr = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	sg = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
	item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	br = ensure("Branch", {"branch": "Jeddah"}, {"branch": "Jeddah", "abbreviation": "JED"})
	br2 = ensure("Branch", {"branch": "Riyadh"}, {"branch": "Riyadh", "abbreviation": "RUH"})
	jt = ensure("Job Type", {"job_type": "Import"}, {"job_type": "Import", "abbreviation": "IMP"})
	jt2 = ensure("Job Type", {"job_type": "Export"}, {"job_type": "Export", "abbreviation": "EXP"})
	mos = ensure("Mode Of Shipment", {"mode_of_shipment": "Sea"}, {"mode_of_shipment": "Sea", "abbreviation": "SEA"})
	mos2 = ensure("Mode Of Shipment", {"mode_of_shipment": "Air"}, {"mode_of_shipment": "Air", "abbreviation": "AIR"})
	sow = ensure("Scope Of Work", {"scope_of_work": "Freight Forwarding"},
		{"scope_of_work": "Freight Forwarding", "abbreviation": "FF", "freight_forwarding": 1})
	for st in ["OPEN", "IN PROGRESS", "COMPLETED", "CLOSED"]:
		ensure("Operations Status", {"status": st}, {"status": st})
	ports = {}
	for pn in ["Jeddah", "Dubai", "Shanghai", "Riyadh", "Dammam"]:
		ports[pn] = ensure("Port", {"port_name": pn}, {"port_name": pn})

	# --- items (service) ---
	items = []
	for nm in ["Freight Charges", "Customs Clearance", "Transportation"]:
		code = ensure("Item", {"item_name": nm}, {
			"item_code": nm, "item_name": nm, "item_group": item_group,
			"is_stock_item": 0, "stock_uom": "Nos",
			"item_defaults": [{"company": company, "income_account": income_acc,
				"expense_account": expense_acc, "default_warehouse": ""}],
		})
		items.append(code)
	log.append(f"items={items}")

	# --- customers ---
	customers = []
	for nm in ["Acme Trading LLC", "Gulf Logistics Co", "Red Sea Traders", "Nile Freight Ltd"]:
		customers.append(ensure("Customer", {"customer_name": nm}, {
			"customer_name": nm, "customer_type": "Company", "branch": br,
			"customer_group": cg, "territory": terr, "credit_period": "30 Days",
			"customer_rating": 4 if "Acme" in nm else 3}))

	# --- suppliers ---
	suppliers = []
	for nm in ["Maersk Line", "DHL Express KSA", "Bayan Customs Broker"]:
		suppliers.append(ensure("Supplier", {"supplier_name": nm}, {
			"supplier_name": nm, "supplier_type": "Company", "supplier_group": sg,
			"branch": br, "is_handling_agent": 1 if "Bayan" in nm else 0}))

	# --- Sales Invoices (submitted) ---
	if frappe.db.exists("Sales Invoice", {"remarks": "FLCS-DEMO"}):
		log.append("sales invoices already seeded — skipping")
	else:
		si_plan = [
			(customers[0], "2026-01-12", items[0], 3, 4500),
			(customers[1], "2026-02-08", items[1], 2, 3200),
			(customers[2], "2026-03-19", items[2], 5, 1800),
			(customers[0], "2026-04-22", items[0], 4, 4200),
			(customers[3], "2026-05-15", items[1], 1, 6800),
			(customers[1], "2026-06-05", items[2], 2, 5100),
		]
		made = []
		for cust, pdate, item, qty, rate in si_plan:
			si = frappe.new_doc("Sales Invoice")
			si.company = company
			si.customer = cust
			si.posting_date = pdate
			si.set_posting_time = 1
			si.due_date = add_days(pdate, 30)
			si.currency = currency
			si.conversion_rate = 1
			si.debit_to = receivable
			si.remarks = "FLCS-DEMO"
			si.append("items", {"item_code": item, "qty": qty, "rate": rate,
				"income_account": income_acc, "cost_center": cost_center})
			si.flags.ignore_permissions = True
			si.insert(ignore_permissions=True)
			si.submit()
			made.append(si.name)
		log.append(f"sales_invoices={made}")
		# pay the first two fully -> Payment Entries (collections + GL)
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
		for sn in made[:3]:
			pe = get_payment_entry("Sales Invoice", sn)
			pe.paid_to = cash
			pe.reference_no = "RCPT-" + sn
			pe.reference_date = nowdate()
			pe.flags.ignore_permissions = True
			pe.insert(ignore_permissions=True)
			pe.submit()
		log.append("customer payments posted")

	# --- Purchase Invoices (submitted) ---
	if frappe.db.exists("Purchase Invoice", {"remarks": "FLCS-DEMO"}):
		log.append("purchase invoices already seeded — skipping")
	else:
		pi_plan = [
			(suppliers[0], "2026-02-02", items[0], 2, 2600),
			(suppliers[1], "2026-03-28", items[2], 3, 1400),
			(suppliers[2], "2026-05-09", items[1], 1, 3900),
		]
		madep = []
		for sup, pdate, item, qty, rate in pi_plan:
			pi = frappe.new_doc("Purchase Invoice")
			pi.company = company
			pi.supplier = sup
			pi.posting_date = pdate
			pi.set_posting_time = 1
			pi.bill_no = "BILL-" + pdate.replace("-", "")
			pi.bill_date = pdate
			pi.currency = currency
			pi.conversion_rate = 1
			pi.credit_to = payable
			pi.remarks = "FLCS-DEMO"
			pi.append("items", {"item_code": item, "qty": qty, "rate": rate,
				"expense_account": expense_acc, "cost_center": cost_center})
			pi.flags.ignore_permissions = True
			pi.insert(ignore_permissions=True)
			pi.submit()
			madep.append(pi.name)
		log.append(f"purchase_invoices={madep}")
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
		for pn in madep[:2]:
			pe = get_payment_entry("Purchase Invoice", pn)
			pe.paid_from = cash
			pe.reference_no = "PAY-" + pn
			pe.reference_date = nowdate()
			pe.flags.ignore_permissions = True
			pe.insert(ignore_permissions=True)
			pe.submit()
		log.append("supplier payments posted")

	# --- Operations (jobs) ---
	if frappe.db.count("Operations") >= 6:
		log.append("operations already present — skipping job seed")
	else:
		etas = [nowdate(), add_days(nowdate(), 1), add_days(nowdate(), 3),
			add_days(nowdate(), 9), add_days(nowdate(), 16), add_days(nowdate(), -4)]
		billings = ["No Invoice", "Cost Sheet Pending", "Pending Billing", "Billed", "Pending Billing", "Billed"]
		job_names = []
		for i in range(6):
			j = frappe.new_doc("Operations")
			j.country = terr
			j.branch = br if i % 2 == 0 else br2
			j.job_type = jt if i % 2 == 0 else jt2
			j.mode_of_shipment = mos if i % 2 == 0 else mos2
			j.scope_of_work = sow
			j.customer = customers[i % len(customers)]
			j.date = nowdate()
			j.eta_date = etas[i]
			j.etd_date = add_days(etas[i], -10)
			j.billing_status = billings[i]
			j.awb_number = f"BL-2026-{1000 + i}"
			j.port_of_loading = list(ports.values())[i % len(ports)]
			j.port_of_destination = list(ports.values())[(i + 1) % len(ports)]
			j.net_weight = 8000 + i * 1500
			j.gross_weight = 8500 + i * 1500
			j.cargo_description = "General merchandise"
			j.append("cost_table", {"item": items[0], "account": expense_acc, "rate": 1000, "cost": 1000 + i * 200})
			j.append("cost_table", {"item": items[2], "account": expense_acc, "rate": 500, "cost": 500 + i * 100})
			j.flags.ignore_mandatory = True
			j.flags.ignore_permissions = True
			j.insert(ignore_permissions=True)
			job_names.append(j.name)
		log.append(f"operations={job_names}")

		# --- Waybills + Job Status for those jobs ---
		for i, jn in enumerate(job_names[:3]):
			wb = frappe.new_doc("Freight Waybill")
			wb.freight_job = jn
			wb.customer = frappe.db.get_value("Operations", jn, "customer")
			wb.waybill_type = "Original"
			wb.status = ["Draft", "Issued", "Approved"][i]
			wb.bl_no = f"BL-2026-{1000 + i}"
			wb.vessel_name = ["MV Jeddah Star", "MV Gulf Pearl", "MV Red Sea"][i]
			wb.issued_date = nowdate()
			wb.flags.ignore_mandatory = True
			wb.flags.ignore_permissions = True
			try:
				wb.insert(ignore_permissions=True)
			except Exception as e:
				log.append(f"waybill skip: {e}")
			js = frappe.new_doc("Freight Job Status")
			js.freight_job = jn
			js.customer = frappe.db.get_value("Operations", jn, "customer")
			js.awb_bl_no = f"BL-2026-{1000 + i}"
			js.status_text = ["Booked", "In Transit", "Arrived"][i]
			js.status_date = nowdate()
			js.flags.ignore_mandatory = True
			js.flags.ignore_permissions = True
			try:
				js.insert(ignore_permissions=True)
			except Exception as e:
				log.append(f"job status skip: {e}")

	frappe.db.commit()
	return " | ".join(log)
