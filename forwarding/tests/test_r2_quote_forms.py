# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 2 stream 5: quote validity and approval (M-07, M-08, R2-24),
Transportation / Clearance numbers (M-13), Transportation layout (M-10),
Job Type list (M-14) and the B7 wording. Everything is rolled back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from forwarding.naming import job_code, service_name
from forwarding.quote import is_expired
from forwarding.quote_to_job import duplicate_quote, make_operations_from_quote
from forwarding.tests.test_customer_360 import make_quote
from forwarding.tests.test_job_360 import CUSTOMER, make
from forwarding.tests.test_r2_documents_dates import make_customer, sales_people


class R2Case(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)


ITEMS = [{"item": "Air Freight", "description": "Air freight", "rate": 100, "units": 1, "amount": 100}]


class TestQuoteApproval(R2Case):
	def test_status_follows_submit_cancel_amend(self):
		quote = make_quote(CUSTOMER, validity_in_days=10, items=ITEMS)
		self.assertEqual((quote.docstatus, quote.status), (0, "Draft"))
		quote.submit()
		self.assertEqual((quote.docstatus, quote.status), (1, "Submitted"))
		quote.cancel()
		self.assertEqual(frappe.db.get_value("Quote", quote.name, "status"), "Cancelled")

		amended = frappe.copy_doc(quote)
		amended.amended_from = quote.name
		amended.docstatus = 0
		amended.insert(ignore_permissions=True)
		self.assertEqual((amended.docstatus, amended.status, amended.amended_from), (0, "Draft", quote.name))
		self.assertEqual(amended.name, f"{quote.name}-1")

	def test_submitted_prices_are_locked_but_validity_extends(self):
		quote = make_quote(CUSTOMER, validity_in_days=2, items=ITEMS, submit=True)
		quote.reload()
		quote.items[0].amount = 999
		with self.assertRaises(frappe.UpdateAfterSubmitError):
			quote.save()

		quote.reload()
		quote.validity = add_days(nowdate(), 30)
		quote.save()
		self.assertEqual(getdate(frappe.db.get_value("Quote", quote.name, "validity")), getdate(add_days(nowdate(), 30)))

	def test_expired_quote_cannot_be_submitted(self):
		quote = make_quote(CUSTOMER, validity_in_days=-1, items=ITEMS)
		with self.assertRaises(frappe.ValidationError):
			quote.submit()
		self.assertEqual(frappe.db.get_value("Quote", quote.name, "docstatus"), 0)

	def test_validity_is_compared_with_the_site_day(self):
		self.assertFalse(is_expired(None))
		self.assertFalse(is_expired(nowdate()), "valid through its last day")
		self.assertTrue(is_expired(add_days(nowdate(), -1)))


class TestJobFromQuote(R2Case):
	def test_only_a_submitted_quote_makes_a_job(self):
		quote = make_quote(CUSTOMER, validity_in_days=5, items=ITEMS)
		with self.assertRaisesRegex(frappe.ValidationError, "not submitted"):
			make_operations_from_quote(quote.name)

		quote.submit()
		job = make_operations_from_quote(quote.name)
		self.assertEqual(job.from_quotation, quote.name)

		quote.cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "cancelled"):
			make_operations_from_quote(quote.name)

	def test_expired_quote_makes_no_job_until_extended(self):
		quote = make_quote(CUSTOMER, validity_in_days=5, items=ITEMS, submit=True)
		# It was valid when approved; the window has since passed (QT260001).
		frappe.db.set_value("Quote", quote.name, "validity", add_days(nowdate(), -4))
		with self.assertRaisesRegex(frappe.ValidationError, "expired"):
			make_operations_from_quote(quote.name)

		quote.reload()
		quote.validity = add_days(nowdate(), 7)
		quote.save()
		self.assertEqual(make_operations_from_quote(quote.name).from_quotation, quote.name)

	def test_open_quote_with_no_validity_makes_a_job(self):
		# A quote is submitted with a validity now (R3-47); one approved
		# before that may still have none.
		quote = make_quote(CUSTOMER, items=ITEMS, submit=True)
		frappe.db.set_value("Quote", quote.name, "validity", None)
		self.assertEqual(make_operations_from_quote(quote.name).customer, CUSTOMER)

	def test_duplicate_of_a_submitted_quote_is_a_draft(self):
		quote = make_quote(CUSTOMER, validity_in_days=1, items=ITEMS, submit=True)
		copy = frappe.get_doc("Quote", duplicate_quote(quote.name))
		self.assertEqual((copy.docstatus, copy.status, copy.amended_from), (0, "Draft", None))


class TestQuoteParties(R2Case):
	def test_salesman_defaults_from_customer_and_both_reach_the_job(self):
		first, second = sales_people()
		customer = make_customer(default_salesperson=first)
		shipper = frappe.db.get_value("Shipper", {}, "name")

		quote = make_quote(customer.name, validity_in_days=5, items=ITEMS, shipper=shipper, submit=True)
		self.assertEqual(quote.salesman, first, "Salesman starts as the customer's default")
		job = make_operations_from_quote(quote.name)
		self.assertEqual(job.salesman, first)
		if shipper:
			self.assertEqual(job.shipper, shipper)

		other = make_quote(customer.name, validity_in_days=5, items=ITEMS, salesman=second, submit=True)
		self.assertEqual(other.salesman, second, "a chosen Salesman is kept")
		self.assertEqual(make_operations_from_quote(other.name).salesman, second)

	def test_quote_has_the_new_fields(self):
		meta = frappe.get_meta("Quote")
		self.assertTrue(meta.is_submittable)
		self.assertEqual(meta.get_field("salesman").options, "Sales Person")
		self.assertEqual(meta.get_field("shipper").options, "Shipper")
		self.assertTrue(meta.get_field("validity").allow_on_submit)

	def test_patch_submits_quotes_that_made_jobs(self):
		from forwarding.patches.v1_0.r2_quote_submittable import set_quote_states

		used = make_quote(CUSTOMER, validity_in_days=-30, items=ITEMS)
		unused = make_quote(CUSTOMER, validity_in_days=5, items=ITEMS)
		make(from_quotation=used.name)
		set_quote_states()

		self.assertEqual(frappe.db.get_value("Quote", used.name, ["docstatus", "status"]), (1, "Submitted"))
		self.assertEqual(frappe.db.get_value("Quote Item", {"parent": used.name}, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Quote", unused.name, ["docstatus", "status"]), (0, "Draft"))


class TestServiceNumbers(R2Case):
	def test_job_code(self):
		self.assertEqual(job_code("R-IM-A-26-07014"), "RIA2607014")
		self.assertEqual(job_code("J-EX-S-26-07015"), "JES2607015")
		self.assertEqual(job_code("ALL-IM-A-26-07050"), "ALLIA2607050", "a multi-letter branch is kept")
		self.assertEqual(job_code("R-IM-A-26-07014-1"), "RIA2607014", "an amendment suffix is dropped")
		self.assertEqual(job_code("OLD/JOB-12"), "OLD/JOB12", "any other shape just loses its hyphens")

	def test_transport_and_clearance_names(self):
		job = make(mode_of_shipment="Sea")
		code = job_code(job.name)

		first = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		second = frappe.get_doc({"doctype": "Transportation", "operations": job.name}).insert(ignore_permissions=True)
		self.assertEqual((first.name, second.name), (f"T{code}", f"T{code}B"))
		self.assertNotIn("-", first.name)

		cc = frappe.get_doc(
			{
				"doctype": "Custom Clearance",
				"operations": job.name,
				"clearance_status": "Draft",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(cc.name, f"C{code}")
		self.assertEqual(service_name("Custom Clearance", "C", job.name), f"C{code}B")

	def test_example_from_the_spec(self):
		with patch("frappe.db.exists", return_value=False):
			self.assertEqual(service_name("Transportation", "T", "R-IM-A-26-07014"), "TRIA2607014")
			self.assertEqual(service_name("Custom Clearance", "C", "R-IM-A-26-07014"), "CRIA2607014")


class TestTransportationLayout(R2Case):
	def test_route_section_order(self):
		fields = [f.fieldname for f in frappe.get_meta("Transportation").fields]
		sections = [
			f.label for f in frappe.get_meta("Transportation").fields if f.fieldtype == "Section Break"
		]
		self.assertEqual(sections, ["Assignment", "Route", "Containers", "Documents", "Costs", "Activity"])
		route = fields[fields.index("location") : fields.index("section_break_7")]
		self.assertEqual(
			route,
			[
				"location",
				"departure_location",
				"departure_location_address",
				"pickup_date",
				"column_break_from",
				"destination_location",
				"destination_location_address",
				"delivery_date",
			],
		)


class TestJobTypesAndBanner(R2Case):
	def test_job_types(self):
		# M-14 withdrawn: LAND TRANSPORT and Others stay; Domestic is gone.
		from forwarding.patches.v1_0 import r2_job_types, r2_job_types_revert

		r2_job_types.execute()  # a no-op now
		r2_job_types_revert.execute()  # idempotent
		types = set(frappe.get_all("Job Type", pluck="name"))
		self.assertTrue({"Import", "Export", "LAND TRANSPORT", "Others"} <= types)
		self.assertNotIn("Domestic", types)
		self.assertEqual(frappe.db.get_value("Job Type", "LAND TRANSPORT", "abbreviation"), "LT")
		self.assertEqual(frappe.db.get_value("Job Type", "Others", "abbreviation"), "OT")

	def test_b7_message_names_services(self):
		from forwarding.patches.v1_0 import r2_customs_banner_services

		frappe.db.set_value(
			"Job Banner Rule",
			"B7",
			"message_template",
			"Customs Clearance is ticked but no Custom Clearance has been created yet",
		)
		r2_customs_banner_services.execute()
		self.assertEqual(
			frappe.db.get_value("Job Banner Rule", "B7", "message_template"),
			"Customs Clearance is in the job's services but no Custom Clearance has been created yet",
		)
