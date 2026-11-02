# Copyright (c) 2026, DVNKS Systems and contributors
"""Batch 4 (addendum page fixes): Simran's Round 3 Addendum items A-22, A-26,
A-28, A-32, A-33 and A-37 — the backend halves. The rest are Vue-only and
checked in the app's tests/store.spec.js."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from forwarding import job_events, party_360
from forwarding.tests.test_job_360 import CUSTOMER, make


def rule(code, applies_to, condition_key, action="view_invoices"):
	return frappe._dict(
		rule_code=code,
		label=code,
		priority=10,
		condition_key=condition_key,
		message_template="{{ ctx.overdue|length }} overdue",
		action=action,
		colour="critical",
		applies_to=applies_to,
	)


class TestOverdueBannerActions(IntegrationTestCase):
	# A-22: the customer / supplier overdue banners act in place.

	def evaluate(self, applies_to, condition_key, overdue):
		with patch("forwarding.banners.get_rules", return_value=[rule("X1", applies_to, condition_key)]):
			return party_360.evaluate_rules(applies_to, {condition_key: bool}, {"overdue": overdue})

	def test_customer_overdue_offers_payment_and_reminder(self):
		overdue = [
			{"name": "SI-B", "due_date": "2026-10-05", "outstanding": 10},
			{"name": "SI-A", "due_date": "2026-10-01", "outstanding": 5},
		]
		(b,) = self.evaluate("Customer", "overdue_invoices", overdue)
		self.assertEqual(b["actions"], ["record_payment", "send_reminder", "view_invoices"])
		self.assertEqual(b["action"], "record_payment")
		self.assertEqual(b["invoices"], ["SI-A", "SI-B"])
		self.assertEqual(b["invoice"], "SI-A")

	def test_supplier_overdue_offers_payment(self):
		(b,) = self.evaluate("Supplier", "overdue_payables", [{"name": "PI-1", "due_date": "2026-10-01"}])
		self.assertEqual(b["actions"], ["record_payment", "view_invoices"])
		self.assertEqual(b["invoice"], "PI-1")

	def test_dismissed_overdue_comes_back_when_the_invoices_change(self):
		one = self.evaluate("Customer", "overdue_invoices", [{"name": "SI-A", "due_date": "2026-10-01", "outstanding": 5}])
		paid_some = self.evaluate("Customer", "overdue_invoices", [{"name": "SI-A", "due_date": "2026-10-01", "outstanding": 2}])
		more = self.evaluate(
			"Customer",
			"overdue_invoices",
			[{"name": "SI-A", "due_date": "2026-10-01"}, {"name": "SI-C", "due_date": "2026-10-09"}],
		)
		self.assertEqual(one[0]["fingerprint"], paid_some[0]["fingerprint"])
		self.assertNotEqual(one[0]["fingerprint"], more[0]["fingerprint"])

	def test_other_banners_keep_their_one_action(self):
		with patch("forwarding.banners.get_rules", return_value=[rule("C3", "Customer", "quote_expiring", "view_quotes")]):
			(b,) = party_360.evaluate_rules("Customer", {"quote_expiring": bool}, {"overdue": []})
		self.assertEqual((b["action"], b["actions"]), ("view_quotes", ["view_quotes"]))
		self.assertNotIn("invoices", b)


class TestPartyDetails(IntegrationTestCase):
	# A-26: the read-only Details tab.

	def test_customer_details(self):
		doc = frappe.get_doc("Customer", CUSTOMER)
		doc.cr_no = "1010"
		doc.tax_id = "0"
		doc.credit_period = "30 Days"
		company = party_360.default_company()
		d = party_360.party_details(doc, company, 5000, salesperson="Someone")
		self.assertIsNone(d["vat"], "a placeholder 0 is no VAT number")
		self.assertEqual((d["cr_no"], d["credit_period"], d["credit_limit"], d["salesperson"]), ("1010", "30 Days", 5000, "Someone"))
		self.assertEqual(d["group"], doc.customer_group)
		self.assertEqual(d["account_type"], "Receivable")
		self.assertNotIn("roles", d)
		if company:
			self.assertTrue(any(a["company"] == company for a in d["accounts"]))

	def test_customer_payload_carries_details(self):
		from forwarding.api import customer_360

		payload = customer_360.build(CUSTOMER)
		self.assertIn("details", payload)
		self.assertIn("name_arabic", payload["details"])

	def test_supplier_details_have_roles(self):
		supplier = frappe.db.get_value("Supplier", {}, "name")
		if not supplier:
			self.skipTest("no supplier on this site")
		from forwarding.api import supplier_360

		details = supplier_360.build(supplier)["details"]
		self.assertEqual(details["account_type"], "Payable")
		self.assertIsInstance(details["roles"], list)


class TestCacheClearedAfterCommit(IntegrationTestCase):
	# A-28: a page read between on_update and the commit cannot leave stale data.

	def test_supplier_cache_dropped_again_after_commit(self):
		key = job_events.supplier_cache_key("_T-B4-SUPP")
		frappe.cache.set_value(key, {"stale": 1})
		job_events.clear_supplier_cache("_T-B4-SUPP")
		self.assertIsNone(frappe.cache.get_value(key))
		# A read that rebuilt the cache before the commit...
		frappe.cache.set_value(key, {"stale": 1})
		frappe.cache.set_value(f"{key}|2026-01-01|", {"stale": 1})
		frappe.db.after_commit.run()
		self.assertIsNone(frappe.cache.get_value(key))
		self.assertIsNone(frappe.cache.get_value(f"{key}|2026-01-01|"))

	def test_customer_cache_dropped_again_after_commit(self):
		key = job_events.customer_cache_key("_T-B4-CUST")
		job_events.clear_customer_cache("_T-B4-CUST")
		frappe.cache.set_value(key, {"stale": 1})
		frappe.db.after_commit.run()
		self.assertIsNone(frappe.cache.get_value(key))


class TestDriverFields(IntegrationTestCase):
	# A-32: a driver's Employee and User fields are hidden.

	def test_employee_and_user_hidden(self):
		from forwarding.patches.v1_0 import b4_hide_driver_employee_user

		b4_hide_driver_employee_user.execute()
		meta = frappe.get_meta("Driver")
		for fieldname in ("employee", "user"):
			self.assertEqual(meta.get_field(fieldname).hidden, 1, fieldname)


class TestVehicleInsuranceDates(IntegrationTestCase):
	# A-33: name the missing insurance date.

	def vehicle(self, **values):
		return frappe.get_doc({"doctype": "Vehicle", "license_plate": "_T-B4-1", **values})

	def test_hook_runs_before_erpnext_validate(self):
		hooks = frappe.get_hooks("doc_events").get("Vehicle", {})
		self.assertIn("forwarding.vehicle.before_validate", hooks.get("before_validate", []))

	def test_end_without_start(self):
		from forwarding.vehicle import before_validate

		with self.assertRaisesRegex(frappe.ValidationError, "Enter the Insurance Start Date"):
			before_validate(self.vehicle(end_date=add_days(nowdate(), -10)))

	def test_future_start_without_end(self):
		from forwarding.vehicle import before_validate

		with self.assertRaisesRegex(frappe.ValidationError, "Enter the Insurance End Date"):
			before_validate(self.vehicle(start_date=add_days(nowdate(), 10)))

	def test_both_or_neither_pass(self):
		from forwarding.vehicle import before_validate

		before_validate(self.vehicle())
		before_validate(self.vehicle(start_date=add_days(nowdate(), -10), end_date=add_days(nowdate(), 10)))
		before_validate(self.vehicle(start_date=add_days(nowdate(), -10)))

	def test_save_says_which_date(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Enter the Insurance Start Date"):
			self.vehicle(end_date=add_days(nowdate(), -10), make="M", model="X").insert(ignore_permissions=True)


class TestJobRulesInOneMessage(IntegrationTestCase):
	# A-37: a save lists every rule it breaks, each in its own words.

	def test_several_rules_one_message(self):
		job = make()
		job.etd_date = add_days(nowdate(), 10)
		job.eta_date = add_days(nowdate(), 8)
		job.gross_weight = 5
		job.net_weight = 10
		job.atd_date = add_days(nowdate(), 3)
		with self.assertRaises(frappe.ValidationError) as caught:
			job.save(ignore_permissions=True)
		message = str(caught.exception)
		self.assertIn("cannot be before", message)
		self.assertIn("Gross weight (5", message)
		self.assertIn("cannot be after today", message)
		self.assertEqual(message.count("<br>"), 2)
		self.assertIsNone(getattr(job, "_rule_errors", None))

	def test_every_cutoff_row_listed_in_the_row_format(self):
		etd = add_days(nowdate(), 10)
		with self.assertRaises(frappe.ValidationError) as caught:
			make(
				job_type="Export",
				mode_of_shipment="Sea",
				etd_date=etd,
				cutoffs=[
					{"milestone": "Rail Cut-off", "deadline": f"{add_days(etd, 2)} 12:00:00"},
					{"milestone": "Rail Cut-off", "deadline": f"{add_days(etd, 3)} 12:00:00"},
				],
			)
		lines = str(caught.exception).split("<br>")
		self.assertTrue(lines[0].startswith("Cut-offs Row #1 (Rail Cut-off): Cut-off can't be after ETD"), lines)
		self.assertTrue(lines[1].startswith("Cut-offs Row #2 (Rail Cut-off): Cut-off can't be after ETD"), lines)

	def test_one_rule_reads_as_before(self):
		job = make()
		job.gross_weight = 5
		job.net_weight = 10
		with self.assertRaisesRegex(frappe.ValidationError, r"^Gross weight \(5"):
			job.save(ignore_permissions=True)
		self.assertNotIn("<br>", frappe.local.message_log[-1] if frappe.local.message_log else "")

	def test_good_save_still_saves(self):
		job = make()
		job.etd_date = job.eta_date = add_days(nowdate(), 5)
		job.save(ignore_permissions=True)
		self.assertIsNone(getattr(job, "_rule_errors", None))

	def test_rule_outside_validate_throws_at_once(self):
		from forwarding.forwarding.doctype.operations.operations import validate_date_order

		job = make()
		job.atd_date = nowdate()
		job.ata_date = add_days(nowdate(), -2)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be before"):
			validate_date_order(job, pairs=(("atd_date", "ata_date"),))
