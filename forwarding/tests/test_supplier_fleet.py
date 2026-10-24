# Copyright (c) 2026, DVNKS Systems and contributors
"""Supplier 360 rates, vehicles and drivers, S5 / S9, Record Payment and the
Purchase Invoice job link (Phase 2 spec SU5-SU7, §5.5-§5.7, §6.2 S5).

Each test makes its own supplier; everything is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from forwarding.api import supplier_360
from forwarding.forwarding.doctype.party_alert_settings.party_alert_settings import get_settings
from forwarding.party_360 import default_company
from forwarding.party_documents import EXPIRED, EXPIRING, NO_EXPIRY, VALID
from forwarding.tests.test_job_360 import ITEM, _first, make
from forwarding.tests.test_supplier_360 import NO_ROLE_USER, codes, fresh, make_bill, make_bill_payment, make_supplier

RATE_KEYS = {
	"name",
	"item_code",
	"item_name",
	"price_list",
	"start_location",
	"end_location",
	"price_list_rate",
	"currency",
	"valid_from",
	"valid_upto",
	"status",
	"days_left",
}
VEHICLE_KEYS = {"name", "license_plate", "make", "model", "insurance_end_date", "expiry_status", "days_left"}
DRIVER_KEYS = {"name", "full_name", "license_number", "expiry_date", "expiry_status", "days_left"}
UNLINKED = "Not linked to a job; this cost will not show on any job or in cost variance"


def in_days(n):
	return add_days(nowdate(), n)


def purchase_items(count):
	items = frappe.get_all(
		"Item", filters={"disabled": 0, "is_purchase_item": 1, "has_variants": 0}, limit=count, pluck="name"
	)
	if len(items) < count:
		raise frappe.DoesNotExistError(f"Test needs {count} purchase items")
	return items


def make_rate(supplier, item, valid_upto, valid_from=None):
	return frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item,
			"price_list": _first("Price List", {"buying": 1, "selling": 0}),
			"price_list_rate": 100,
			"supplier": supplier,
			"valid_from": valid_from or in_days(-60),
			"valid_upto": valid_upto,
		}
	).insert(ignore_permissions=True)


def make_vehicle(transporter, end_date, plate=None):
	return frappe.get_doc(
		{
			"doctype": "Vehicle",
			"license_plate": plate or f"T-{frappe.generate_hash(length=6)}",
			"make": "Volvo",
			"model": "FH",
			"last_odometer": 1,
			"fuel_type": "Diesel",
			"uom": _first("UOM"),
			"start_date": add_days(end_date, -365) if end_date else None,
			"end_date": end_date,
			"transporter": transporter,
		}
	).insert(ignore_permissions=True)


def make_driver(transporter, expiry_date, name=None):
	return frappe.get_doc(
		{
			"doctype": "Driver",
			"full_name": name or f"Driver {frappe.generate_hash(length=5)}",
			"status": "Active",
			"license_number": "L-1",
			"transporter": transporter,
			"expiry_date": expiry_date,
		}
	).insert(ignore_permissions=True)


def banner(payload, code):
	return next((b for b in payload["banners"] if b["code"] == code), None)


def messages():
	return " ".join(str(m.get("message") if isinstance(m, dict) else m) for m in frappe.message_log)


class TestSupplierFleet(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.settings = get_settings()

	# -- Rates (SU5, §5.7) --------------------------------------------------------------

	def test_rate_status_boundaries_and_order(self):
		supplier = make_supplier(is_shipping_line=1).name
		days = self.settings.rate_expiry_days
		a, b, c, d, e = purchase_items(5)
		make_rate(supplier, a, None)  # No expiry
		make_rate(supplier, b, in_days(days + 1))  # Valid
		make_rate(supplier, c, in_days(days))  # Expiring, last day included
		make_rate(supplier, d, in_days(-1), valid_from=in_days(-60))  # Expired
		make_rate(supplier, e, in_days(0))  # Expiring today

		payload = fresh(supplier)
		rates = payload["rates"]
		self.assertEqual(set(rates[0]), RATE_KEYS)
		self.assertEqual(
			[(r["item_code"], r["status"]) for r in rates],
			[(d, EXPIRED), (e, EXPIRING), (c, EXPIRING), (b, VALID), (a, NO_EXPIRY)],
		)
		self.assertEqual([r["days_left"] for r in rates], [-1, 0, days, days + 1, None])
		kpis = payload["kpis"]
		self.assertEqual((kpis["rates_count"], kpis["rates_expiring"], kpis["rates_expired"]), (5, 2, 1))

	def test_rates_lane_fields_present(self):
		supplier = make_supplier(is_airline=1).name
		make_rate(supplier, ITEM, in_days(90))
		rate = fresh(supplier)["rates"][0]
		# start_location / end_location are custom Port links on this site.
		self.assertIsNone(rate["start_location"])
		self.assertIsNone(rate["end_location"])
		self.assertEqual(rate["status"], VALID)

	def test_selling_prices_are_not_rates(self):
		supplier = make_supplier(is_shipping_line=1).name
		self.assertEqual(fresh(supplier)["rates"], [])

	# -- Tab flags ------------------------------------------------------------------------

	def test_show_rates_and_show_fleet_per_role(self):
		cases = {
			"is_shipping_line": (True, False),
			"is_airline": (True, False),
			"is_overseas_agent": (True, False),
			"is_transporter": (True, True),
			"is_broker": (False, False),
			"is_handling_agent": (False, False),
		}
		for role, expected in cases.items():
			payload = fresh(make_supplier(**{role: 1}).name)
			self.assertEqual((payload["show_rates"], payload["show_fleet"]), expected, role)
		payload = fresh(make_supplier().name)
		self.assertEqual((payload["show_rates"], payload["show_fleet"]), (False, False))

	# -- Vehicles and drivers (SU6, §5.5) -------------------------------------------------

	def test_vehicle_transporter_field(self):
		field = frappe.get_meta("Vehicle").get_field("transporter")
		self.assertEqual((field.fieldtype, field.options), ("Link", "Supplier"))
		self.assertIn("is_transporter", field.link_filters)

	def test_vehicles_and_drivers_rows_and_status(self):
		supplier = make_supplier(is_transporter=1).name
		days = self.settings.document_expiry_days
		valid = make_vehicle(supplier, in_days(days + 1))
		expiring = make_vehicle(supplier, in_days(days))
		none = make_vehicle(supplier, None)
		expired = make_driver(supplier, in_days(-3))
		ok = make_driver(supplier, in_days(200))
		make_vehicle(make_supplier(is_transporter=1).name, in_days(1))  # someone else's

		payload = fresh(supplier)
		vehicles, drivers = payload["vehicles"], payload["drivers"]
		self.assertEqual(set(vehicles[0]), VEHICLE_KEYS)
		self.assertEqual(set(drivers[0]), DRIVER_KEYS)
		self.assertEqual(
			[(v["name"], v["expiry_status"]) for v in vehicles],
			[(expiring.name, EXPIRING), (valid.name, VALID), (none.name, NO_EXPIRY)],
		)
		self.assertEqual(vehicles[0]["insurance_end_date"], str(getdate(in_days(days))))
		self.assertEqual(
			[(d["name"], d["expiry_status"], d["days_left"]) for d in drivers],
			[(expired.name, EXPIRED, -3), (ok.name, VALID, 200)],
		)
		kpis = payload["kpis"]
		self.assertEqual((kpis["fleet_count"], kpis["fleet_expiring"], kpis["fleet_expired"]), (5, 1, 1))

	# -- S5 / S9 ---------------------------------------------------------------------------

	def test_one_expiring_vehicle_raises_s5_only(self):
		supplier = make_supplier(is_transporter=1).name
		make_vehicle(supplier, in_days(10), plate="ABC-123")
		payload = fresh(supplier)
		s5 = banner(payload, "S5")
		self.assertEqual((s5["colour"], s5["action"]), ("warning", "view_fleet"))
		self.assertIn("Vehicle ABC-123 insurance expires", s5["message"])
		self.assertNotIn("S9", codes(payload))

	def test_one_expired_driver_raises_s9_only(self):
		supplier = make_supplier(is_transporter=1).name
		make_driver(supplier, in_days(-5), name="Ali Test")
		payload = fresh(supplier)
		s9 = banner(payload, "S9")
		self.assertEqual((s9["colour"], s9["action"]), ("critical", "view_fleet"))
		self.assertIn("Driver Ali Test licence expired", s9["message"])
		self.assertNotIn("S5", codes(payload))

	def test_several_rows_are_counted(self):
		supplier = make_supplier(is_transporter=1).name
		make_vehicle(supplier, in_days(3))
		make_driver(supplier, in_days(4))
		make_driver(supplier, in_days(-1))
		make_vehicle(supplier, in_days(-2))
		payload = fresh(supplier)
		days = self.settings.document_expiry_days
		self.assertEqual(
			banner(payload, "S5")["message"], f"2 vehicle / driver documents expire within {days} days"
		)
		self.assertEqual(banner(payload, "S9")["message"], "2 vehicle / driver documents have expired")

	def test_fleet_banners_only_for_transporters(self):
		supplier = make_supplier(is_broker=1).name
		make_driver(supplier, in_days(-5))
		make_driver(supplier, in_days(5))
		payload = fresh(supplier)
		self.assertFalse({"S5", "S9"} & set(codes(payload)))
		# The rows are still listed; only the tab flag and banners follow the role.
		self.assertEqual(len(payload["drivers"]), 2)

	def test_valid_fleet_raises_nothing(self):
		supplier = make_supplier(is_transporter=1).name
		make_vehicle(supplier, in_days(300))
		make_driver(supplier, None)
		self.assertFalse({"S5", "S9"} & set(codes(fresh(supplier))))

	# -- Record Payment (SU7) ------------------------------------------------------------

	def test_record_payment_references_and_amount(self):
		supplier = make_supplier(is_transporter=1).name
		later = make_bill(supplier, 300, due_in_days=20)
		oldest = make_bill(supplier, 200, due_in_days=-10)
		part = make_bill(supplier, 500, due_in_days=5)
		make_bill_payment(part, 150)
		make_bill(supplier, 999, due_in_days=1, submit=False)  # draft: not owed

		pe = supplier_360.record_payment(supplier)
		self.assertEqual((pe["doctype"], pe["payment_type"]), ("Payment Entry", "Pay"))
		self.assertEqual((pe["party_type"], pe["party"]), ("Supplier", supplier))
		self.assertEqual(pe["company"], default_company())
		self.assertTrue(pe["paid_from"])
		self.assertTrue(pe["paid_to"])
		self.assertFalse(pe.get("docstatus"))
		self.assertFalse(frappe.db.exists("Payment Entry", {"party": supplier, "docstatus": 0}))
		refs = [(r["reference_name"], r["outstanding_amount"], r["allocated_amount"]) for r in pe["references"]]
		self.assertEqual(refs, [(oldest.name, 200, 200), (part.name, 350, 350), (later.name, 300, 300)])
		self.assertEqual(pe["paid_amount"], 850)
		self.assertEqual(pe["received_amount"], 850)

	def test_record_payment_with_nothing_owed(self):
		supplier = make_supplier(is_transporter=1).name
		pe = supplier_360.record_payment(supplier)
		self.assertEqual(pe["references"], [])
		self.assertEqual(pe["paid_amount"], 0)
		self.assertEqual(pe["party"], supplier)

	def test_record_payment_needs_payment_entry_create(self):
		supplier = make_supplier().name
		if not frappe.db.exists("User", NO_ROLE_USER):
			frappe.get_doc(
				{"doctype": "User", "email": NO_ROLE_USER, "first_name": "No Role", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(NO_ROLE_USER)
		self.assertRaises(frappe.PermissionError, supplier_360.record_payment, supplier)

	# -- Purchase Invoice (§5.6) ------------------------------------------------------------

	def test_unlinked_bill_from_a_role_supplier_warns(self):
		supplier = make_supplier(is_transporter=1).name
		frappe.clear_messages()
		pi = make_bill(supplier, 100, submit=False)
		self.assertIn(UNLINKED, messages())
		self.assertEqual(pi.docstatus, 0)  # saved: a warning, not a block

	def test_no_warning_without_roles_or_with_a_job(self):
		frappe.clear_messages()
		make_bill(make_supplier().name, 100, submit=False)
		self.assertNotIn(UNLINKED, messages())

		job = make()
		frappe.clear_messages()
		make_bill(make_supplier(is_transporter=1).name, 100, job=job.name, submit=False)
		self.assertNotIn(UNLINKED, messages())

	def test_job_fills_project_and_cost_center(self):
		job = make()
		company = default_company()
		default_cc = frappe.get_cached_value("Company", company, "cost_center")
		cost_center = _first("Cost Center", {"company": company, "is_group": 0, "name": ["!=", default_cc]})
		frappe.db.set_value("Operations", job.name, "cost_center", cost_center)
		job.reload()
		self.assertTrue(frappe.db.exists("Project", job.project))

		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": company,
				"supplier": make_supplier().name,
				"operations": job.name,
				"bill_no": f"B-{frappe.generate_hash(length=6)}",
				"items": [{"item_code": ITEM, "qty": 1, "rate": 50}],
			}
		).insert(ignore_permissions=True)
		self.assertEqual((pi.project, pi.cost_center), (job.project, cost_center))
		self.assertEqual((pi.items[0].project, pi.items[0].cost_center), (job.project, cost_center))

	def test_job_does_not_overwrite_chosen_values(self):
		job = make()
		company = default_company()
		default_cc = frappe.get_cached_value("Company", company, "cost_center")
		leaves = frappe.get_all(
			"Cost Center", filters={"company": company, "is_group": 0, "name": ["!=", default_cc]}, pluck="name"
		)
		if len(leaves) < 2:
			self.skipTest("Needs two cost centers")
		frappe.db.set_value("Operations", job.name, "cost_center", leaves[0])
		other_project = frappe.db.get_value("Project", {"name": ["!=", job.reload().project]}, "name")

		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": company,
				"supplier": make_supplier().name,
				"operations": job.name,
				"bill_no": f"B-{frappe.generate_hash(length=6)}",
				"project": other_project,
				"cost_center": leaves[1],
				"items": [{"item_code": ITEM, "qty": 1, "rate": 50, "cost_center": leaves[1]}],
			}
		).insert(ignore_permissions=True)
		self.assertEqual((pi.project, pi.cost_center), (other_project, leaves[1]))
		self.assertEqual(pi.items[0].cost_center, leaves[1])
		# The item's empty project still comes from the job.
		self.assertEqual(pi.items[0].project, job.project)
