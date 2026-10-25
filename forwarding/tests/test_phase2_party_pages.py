# Copyright (c) 2026, DVNKS Systems and contributors
"""Phase 2: Customer & Supplier pages (backend P1 items).

Supplier roles and Tax ID rule, Shipping Line / Carrier -> Supplier links,
cost row suppliers, the wider supplier job list, Cost variance, the new
banners (C5, S4, S6), the Statement of Account, the cache hooks and the
patches. Everything is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding.api import statement
from forwarding.tests.test_customer_360 import fresh as fresh_customer
from forwarding.tests.test_customer_360 import make_customer as _make_customer
from forwarding.tests.test_customer_360 import make_invoice
from forwarding.tests.test_job_360 import ITEM, _first, make, make_payment
from forwarding.tests.test_supplier_360 import (
	codes,
	fresh,
	is_cached,
	make_bill,
	make_clearance,
	make_supplier,
	make_transport,
)


def make_customer(**values):
	# CR No. and a VAT number are mandatory on this site's Customer.
	return _make_customer(
		**{"cr_no": "1010999999", "custom_vat_registration_number": "300000000000003", **values}
	)


def jobs_of(payload):
	return {j["name"]: j["roles"] for j in payload["jobs"]}


class TestPhase2PartyPages(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.supplier = make_supplier()

	# -- Supplier fields (§4, §5.1) ----------------------------------------------

	def test_role_pills_and_header(self):
		s = make_supplier(is_transporter=1, is_broker=1, is_overseas_agent=1, cr_no="1010101010")
		header = fresh(s.name)["supplier"]
		self.assertEqual(header["roles"], ["Transporter", "Broker", "Overseas Agent"])
		self.assertEqual(header["cr_no"], "1010101010")
		self.assertIn("payment_terms", header)
		self.assertIn("primary_contact", header)
		self.assertEqual(fresh(self.supplier.name)["supplier"]["roles"], [])

	def test_tax_id_mandatory_only_for_saudi(self):
		make_supplier(country="United Arab Emirates", tax_id=None)
		self.assertRaises(frappe.MandatoryError, make_supplier, country="Saudi Arabia", tax_id=None)

	def test_roles_section_on_details_tab(self):
		meta = frappe.get_meta("Supplier")
		order = [f.fieldname for f in meta.fields]
		section = order.index("roles_section")
		self.assertLess(section, order.index("contact_and_address_tab"))
		for field in ("is_transporter", "is_handling_agent", "is_broker", "is_shipping_line", "is_airline", "is_overseas_agent"):
			self.assertGreater(order.index(field), section, field)
			self.assertLess(order.index(field), order.index("defaults_section"), field)
		self.assertTrue(meta.get_field("gst_category").hidden)
		# ERPNext's supplier_type (Company / Individual) is untouched.
		self.assertFalse(frappe.db.exists("Custom Field", {"dt": "Supplier", "fieldname": "supplier_type"}))

	# -- Shipping Line / Carrier (§4) ---------------------------------------------

	def test_shipping_line_and_carrier_link_tick_roles_and_list_jobs(self):
		line = frappe.get_doc(
			{"doctype": "Shipping Line", "shipping_line": f"P2 Line {frappe.generate_hash(length=5)}", "supplier": self.supplier.name}
		).insert(ignore_permissions=True)
		carrier = frappe.get_doc(
			{"doctype": "Carrier", "carrier": f"P2 Air {frappe.generate_hash(length=5)}", "supplier": self.supplier.name}
		).insert(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("Supplier", self.supplier.name, ["is_shipping_line", "is_airline"]), (1, 1)
		)

		sea = make(mode_of_shipment="Sea", shipping_line=line.name)
		air = make(carrier=carrier.name)
		payload = fresh(self.supplier.name)
		self.assertEqual(jobs_of(payload)[sea.name], ["Shipping Line"])
		self.assertEqual(jobs_of(payload)[air.name], ["Airline"])
		self.assertEqual(payload["supplier"]["roles"], ["Shipping Line", "Airline"])

	def test_linking_a_line_clears_the_supplier_cache(self):
		fresh(self.supplier.name)
		frappe.get_doc(
			{"doctype": "Shipping Line", "shipping_line": f"P2 Line {frappe.generate_hash(length=5)}", "supplier": self.supplier.name}
		).insert(ignore_permissions=True)
		self.assertFalse(is_cached(self.supplier.name))

	# -- Cost row supplier (§5.2) ---------------------------------------------------

	def test_new_cost_rows_default_to_the_transporter(self):
		job = make()
		t = make_transport(job, self.supplier.name)
		t.append("cost_table", {"item": ITEM, "cost": 300})
		t.save(ignore_permissions=True)
		self.assertEqual(t.cost_table[0].supplier, self.supplier.name)
		# The job's copy of the row carries it too.
		copy = frappe.db.get_value("Cost Table", t.cost_table[0].ref_id, ["parent", "supplier"])
		self.assertEqual(copy, (job.name, self.supplier.name))

		# Cleared on an existing row: stays cleared.
		t.cost_table[0].supplier = None
		t.save(ignore_permissions=True)
		t.reload()
		self.assertFalse(t.cost_table[0].supplier)

	def test_clearance_cost_rows_default_to_transporter_then_broker(self):
		broker = make_supplier()
		job = make()
		both = make_clearance(job, broker=broker.name, transporter=self.supplier.name)
		both.append("cost_table", {"item": ITEM, "cost": 100})
		both.save(ignore_permissions=True)
		self.assertEqual(both.cost_table[0].supplier, self.supplier.name)

		only_broker = make_clearance(make(), broker=broker.name)
		only_broker.append("cost_table", {"item": ITEM, "cost": 100})
		only_broker.save(ignore_permissions=True)
		self.assertEqual(only_broker.cost_table[0].supplier, broker.name)

	def test_job_cost_rows_have_no_default(self):
		job = make(cost_table=[{"item": ITEM, "cost": 50}])
		self.assertFalse(job.cost_table[0].supplier)

	# -- Supplier jobs (§6) ------------------------------------------------------------

	def test_jobs_from_cost_rows_and_bills_and_cancelled_left_out(self):
		by_cost = make(cost_table=[{"item": ITEM, "cost": 50, "supplier": self.supplier.name}])
		by_service_cost = make()
		t = make_transport(by_service_cost, make_supplier().name)
		t.append("cost_table", {"item": ITEM, "cost": 70, "supplier": self.supplier.name})
		t.save(ignore_permissions=True)
		by_bill = make()
		make_bill(self.supplier.name, 100, due_in_days=10, job=by_bill.name)
		cancelled = make(cost_table=[{"item": ITEM, "cost": 50, "supplier": self.supplier.name}])
		frappe.db.set_value("Operations", cancelled.name, "operations_status", "Cancelled")

		jobs = jobs_of(fresh(self.supplier.name))
		self.assertEqual(jobs[by_cost.name], ["Supplier"])
		self.assertEqual(jobs[by_service_cost.name], ["Supplier"])
		self.assertEqual(jobs[by_bill.name], ["Supplier"])
		self.assertNotIn(cancelled.name, jobs)

	# -- Cost variance and S6 (§6.1) ------------------------------------------------------

	def test_cost_variance_ten_percent_raises_s6(self):
		job = make(cost_table=[{"item": ITEM, "cost": 1000, "supplier": self.supplier.name}])
		make_bill(self.supplier.name, 1100, due_in_days=10, job=job.name)
		on_estimate = make(cost_table=[{"item": ITEM, "cost": 500, "supplier": self.supplier.name}])
		make_bill(self.supplier.name, 510, due_in_days=10, job=on_estimate.name)
		make_bill(self.supplier.name, 80, due_in_days=10, job=make().name)

		payload = fresh(self.supplier.name)
		cv = payload["kpis"]["cost_variance"]
		self.assertEqual(cv["estimated"], 1500)
		self.assertEqual(cv["invoiced"], 1610)
		self.assertAlmostEqual(cv["pct"], 7.33, places=2)
		self.assertEqual((cv["jobs_compared"], cv["jobs_over_estimate"], cv["jobs_without_estimate"]), (2, 1, 1))
		self.assertEqual(cv["threshold"], 5)
		self.assertIn("open_services", payload["kpis"])

		s6 = next(b for b in payload["banners"] if b["code"] == "S6")
		self.assertEqual((s6["colour"], s6["action"]), ("warning", "view_jobs"))
		self.assertIn(job.name, s6["message"])
		self.assertIn("10", s6["message"])

	def test_threshold_comes_from_settings(self):
		job = make(cost_table=[{"item": ITEM, "cost": 1000, "supplier": self.supplier.name}])
		make_bill(self.supplier.name, 1100, due_in_days=10, job=job.name)
		settings = frappe.get_single("Party Alert Settings")
		settings.cost_variance_threshold = 15
		settings.save(ignore_permissions=True)
		payload = fresh(self.supplier.name)
		self.assertEqual(payload["kpis"]["cost_variance"]["jobs_over_estimate"], 0)
		self.assertNotIn("S6", codes(payload))

	# -- S4 rates expiring --------------------------------------------------------------

	def test_buying_rate_ending_soon_raises_s4(self):
		price_list = _first("Price List", {"buying": 1})
		price = frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": ITEM,
				"price_list": price_list,
				"price_list_rate": 250,
				"supplier": self.supplier.name,
				"valid_from": add_days(nowdate(), -30),
				"valid_upto": add_days(nowdate(), 5),
			}
		).insert(ignore_permissions=True)
		self.assertTrue(price.buying)
		self.assertFalse(is_cached(self.supplier.name))

		payload = fresh(self.supplier.name)
		s4 = next(b for b in payload["banners"] if b["code"] == "S4")
		self.assertEqual((s4["colour"], s4["action"]), ("warning", "view_rates"))
		self.assertIn(ITEM, s4["message"])

		frappe.db.set_value("Item Price", price.name, "valid_upto", add_days(nowdate(), 20))
		self.assertNotIn("S4", codes(fresh(self.supplier.name)))

	# -- C5 delivered, not invoiced -------------------------------------------------------

	def test_customer_job_delivered_not_invoiced_raises_c5(self):
		customer = make_customer()
		job = make(customer=customer.name)
		self.assertNotIn("C5", codes(fresh_customer(customer.name)))

		frappe.db.set_value("Operations", job.name, "operations_status", "Delivered")
		payload = fresh_customer(customer.name)
		c5 = next(b for b in payload["banners"] if b["code"] == "C5")
		self.assertEqual((c5["colour"], c5["action"]), ("critical", "view_jobs"))
		self.assertIn(job.name, c5["message"])

	def test_customer_header_prefill_fields(self):
		branch = _first("Branch")
		salesman = _first("Sales Person", {"is_group": 0})
		customer = make_customer(branch=branch, sales_team=[{"sales_person": salesman, "allocated_percentage": 100}])
		header = fresh_customer(customer.name)["customer"]
		self.assertEqual((header["branch"], header["default_salesman"]), (branch, salesman))

	def test_customer_group_parent(self):
		group = _first("Customer Group", {"is_group": 0})
		customer = make_customer(customer_group=group)
		header = fresh_customer(customer.name)["customer"]
		self.assertEqual(
			header["customer_group_parent"],
			frappe.db.get_value("Customer Group", group, "parent_customer_group") or None,
		)
		root = frappe.db.get_value("Customer Group", {"parent_customer_group": ["is", "not set"]}, "name")
		frappe.db.set_value("Customer", customer.name, "customer_group", root)
		self.assertIsNone(fresh_customer(customer.name)["customer"]["customer_group_parent"])

	def test_job_purchase_invoice_rows_name_the_supplier(self):
		from forwarding.api import job_360
		from forwarding.job_events import cache_key

		job = make()
		pi = make_bill(self.supplier.name, 100, due_in_days=10, job=job.name)
		frappe.cache.delete_value(cache_key(job.name))
		row = next(r for r in job_360.get(job.name)["invoices"]["purchase"] if r["name"] == pi.name)
		self.assertEqual((row["supplier"], row["supplier_name"]), (self.supplier.name, self.supplier.supplier_name))

	def test_job_names_the_carrier_suppliers(self):
		from forwarding.api import job_360
		from forwarding.job_events import cache_key

		line = frappe.get_doc(
			{"doctype": "Shipping Line", "shipping_line": f"P2 Line {frappe.generate_hash(length=5)}", "supplier": self.supplier.name}
		).insert(ignore_permissions=True)
		carrier = frappe.get_doc({"doctype": "Carrier", "carrier": f"P2 Air {frappe.generate_hash(length=5)}"}).insert(
			ignore_permissions=True
		)
		job = make(mode_of_shipment="Sea", shipping_line=line.name, carrier=carrier.name, handling_agent=self.supplier.name)
		frappe.cache.delete_value(cache_key(job.name))
		got = job_360.get(job.name)["job"]
		self.assertEqual(
			(got["shipping_line_supplier"], got["carrier"], got["carrier_supplier"], got["handling_agent"]),
			(self.supplier.name, carrier.name, None, self.supplier.name),
		)

	def test_supplier_tile_patch_swaps_only_open_services(self):
		from forwarding.patches.v1_0.supplier_tile_cost_variance import replace_tile

		props = {
			"freight_page": "supplier_360",
			"tiles": [
				{"key": "payables", "label": "Owed", "tab": "jobs"},
				{"key": "open_services", "label": "Services open", "tab": "services", "hidden": 1},
				{"key": "active_jobs", "label": "Active jobs", "tab": "jobs"},
			],
			"actions": [{"key": "edit", "label": "Edit"}],
		}
		new = replace_tile(props)
		self.assertEqual(
			new["tiles"],
			[
				{"key": "payables", "label": "Owed", "tab": "jobs"},
				{"key": "cost_variance", "label": "Cost variance", "tab": "jobs", "hidden": 1},
				{"key": "active_jobs", "label": "Active jobs", "tab": "jobs"},
			],
		)
		self.assertEqual(new["actions"], props["actions"])
		self.assertIsNone(replace_tile(new), "running again changes nothing")

		from forwarding.api import ui_config

		self.assertIn("cost_variance", [t["key"] for t in ui_config.default_page("supplier_360")["tiles"]])
		self.assertNotIn("open_services", [t["key"] for t in ui_config.default_page("supplier_360")["tiles"]])

	def test_job_banner_rules_stay_on_their_page(self):
		from forwarding import banners

		self.assertEqual({r.rule_code[0] for r in banners.get_rules()}, {"B"})
		self.assertEqual({r.rule_code[0] for r in banners.get_rules("Customer")}, {"C"})

	# -- Statement of Account (CU2 / SU8) -------------------------------------------------

	def test_customer_statement(self):
		customer = make_customer()
		old = make_invoice(customer.name, 300, due_in_days=-75)
		si = make_invoice(customer.name, 1000, due_in_days=-10)
		make_payment(si, 400)

		s = statement.get("Customer", customer.name, from_date=add_days(nowdate(), -30), to_date=nowdate())
		self.assertEqual(s["opening_balance"], 300)
		self.assertEqual([r["type"] for r in s["rows"]], ["Invoice", "Payment"])
		self.assertEqual([r["balance"] for r in s["rows"]], [1300, 900])
		self.assertEqual(s["closing_balance"], 900)
		self.assertEqual((s["total_debit"], s["total_credit"]), (1000, 400))
		self.assertEqual(s["ageing"], {"0-30": 600, "31-60": 0, "61-90": 300, "90+": 0, "total": 900})
		self.assertEqual(s["balance_label"], "Receivable")
		self.assertTrue(old.name)

	def test_supplier_statement_is_payable_positive(self):
		pi = make_bill(self.supplier.name, 500, due_in_days=-40)
		s = statement.get("Supplier", self.supplier.name)
		self.assertEqual(s["rows"][0]["voucher_no"], pi.name)
		self.assertEqual(s["closing_balance"], 500)
		self.assertEqual(s["ageing"]["31-60"], 500)
		self.assertEqual(s["balance_label"], "Payable")

	def test_statement_pdf_html_and_email(self):
		customer = make_customer()
		make_invoice(customer.name, 1000, due_in_days=5)

		html = statement.get_html("Customer", customer.name)["html"]
		self.assertIn(customer.customer_name, html)
		self.assertIn("Opening balance", html)

		statement.download_pdf("Customer", customer.name)
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))
		self.assertEqual(frappe.local.response.type, "download")

		sent = statement.send_email("Customer", customer.name, recipients="soa-test@example.com")
		self.assertEqual(sent["recipients"], ["soa-test@example.com"])
		queued = frappe.get_last_doc("Email Queue", filters={"reference_name": customer.name})
		self.assertEqual(queued.reference_doctype, "Customer")

	def test_statement_permission_gate(self):
		self.assertRaises(frappe.ValidationError, statement.get, "Employee", "x")
		user = "soa-norole@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "SOA"}).insert(ignore_permissions=True)
		frappe.set_user(user)
		self.assertRaises(frappe.PermissionError, statement.get, "Supplier", self.supplier.name)

	# -- Cache hooks (§6.3) ----------------------------------------------------------------

	def test_fleet_changes_clear_the_transporter_cache(self):
		fresh(self.supplier.name)
		frappe.get_doc(
			{
				"doctype": "Driver",
				"full_name": f"P2 Driver {frappe.generate_hash(length=5)}",
				"transporter": self.supplier.name,
			}
		).insert(ignore_permissions=True)
		self.assertFalse(is_cached(self.supplier.name))

	def test_job_cost_row_change_clears_supplier_cache(self):
		job = make()
		fresh(self.supplier.name)
		job.append("cost_table", {"item": ITEM, "cost": 10, "supplier": self.supplier.name})
		job.save(ignore_permissions=True)
		self.assertFalse(is_cached(self.supplier.name))

	# -- Patches ---------------------------------------------------------------------------

	def test_backfill_cost_row_suppliers(self):
		from forwarding.patches.v1_0 import backfill_cost_row_suppliers

		job = make()
		t = make_transport(job, self.supplier.name)
		t.append("cost_table", {"item": ITEM, "cost": 300})
		t.save(ignore_permissions=True)
		row, copy = t.cost_table[0].name, t.cost_table[0].ref_id
		for name in (row, copy):
			frappe.db.set_value("Cost Table", name, "supplier", None)

		backfill_cost_row_suppliers.execute()
		self.assertEqual(frappe.db.get_value("Cost Table", row, "supplier"), self.supplier.name)
		self.assertEqual(frappe.db.get_value("Cost Table", copy, "supplier"), self.supplier.name)

	def test_link_carriers_matches_names_ignoring_case(self):
		from forwarding.patches.v1_0 import link_carriers_to_suppliers

		name = f"P2 Ocean {frappe.generate_hash(length=5)}"
		supplier = make_supplier(supplier_name=name)
		line = frappe.get_doc({"doctype": "Shipping Line", "shipping_line": f"  {name.upper()} "}).insert(
			ignore_permissions=True
		)
		# The patch's schema steps (reload_doc, syncing custom/supplier.json)
		# are already applied by migrate, and their DDL commits the test
		# transaction implicitly: every job this class had made so far stayed
		# behind as a stray draft. Only the matching is under test here.
		with (
			patch("builtins.print"),
			patch.object(frappe, "reload_doc"),
			patch.object(link_carriers_to_suppliers, "_sync_supplier_customizations"),
		):
			link_carriers_to_suppliers.execute()
		self.assertEqual(frappe.db.get_value("Shipping Line", line.name, "supplier"), supplier.name)
		self.assertEqual(frappe.db.get_value("Supplier", supplier.name, "is_shipping_line"), 1)
