# Copyright (c) 2026, DVNKS Systems and contributors
"""Job 360: billing status, banners, the get() payload and record_actual().

Runs against the site's own masters (company, customer, item, accounts), so
it needs a site with the demo data; everything it creates is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from forwarding import banners
from forwarding.api import job_360
from forwarding.forwarding.doctype.operations.operations import get_cutoff_status
from forwarding.job_events import cache_key, get_billing_status

CUSTOMER = "Demo Customer 09"
ITEM = "Air Freight"


def _first(doctype, filters=None):
	name = frappe.db.get_value(doctype, filters or {}, "name")
	if not name:
		raise frappe.DoesNotExistError(f"Test needs a {doctype} matching {filters}")
	return name


TEST_SCOPE = "_Test Scope Any Service"


def any_service_scope():
	"""A Scope of Work with no Allowed Service Types, so it allows every
	service: a new job needs a scope (M-06). The site's own such scope is used
	when it has one, so a test record that outlives a run (something in the
	suite commits mid-run) is not left in every user's Scope picker."""
	unrestricted = frappe.qb.DocType("Scope Of Work")
	rows = frappe.qb.DocType("Scope Of Work Service Type")
	existing = (
		frappe.qb.from_(unrestricted)
		.left_join(rows)
		.on(rows.parent == unrestricted.name)
		.select(unrestricted.name)
		.where(rows.name.isnull())
		.orderby(unrestricted.name)
		.limit(1)
		.run(pluck=True)
	)
	if existing:
		return existing[0]
	if not frappe.db.exists("Scope Of Work", TEST_SCOPE):
		frappe.get_doc({"doctype": "Scope Of Work", "scope_of_work": TEST_SCOPE, "abbreviation": "TSA"}).insert(
			ignore_permissions=True
		)
	return TEST_SCOPE


def make(**values):
	"""An Operations job with the site's first branch / mode / job type."""
	job = frappe.get_doc(
		{
			"doctype": "Operations",
			"company": _first("Company"),
			"customer": CUSTOMER,
			"branch": _first("Branch", {"abbreviation": ["is", "set"]}),
			"job_type": values.pop("job_type", "Import"),
			"mode_of_shipment": values.pop("mode_of_shipment", "Air"),
			"scope_of_work": values.pop("scope_of_work", None) or any_service_scope(),
			"date": nowdate(),
			**values,
		}
	)
	job.insert(ignore_permissions=True)
	return job


def add_estimate(job, selling=1000, cost=0):
	"""Give a draft job the estimate it needs before it can be submitted (M-02)."""
	job.append("cost_table", {"item_name": "Estimate", "rate": selling, "cost": cost})
	job.save(ignore_permissions=True)
	return job


def submit_job(job):
	"""Submit a job, adding an estimate row first when it has none."""
	if not any((row.rate or 0) > 0 for row in job.cost_table):
		add_estimate(job)
	job.submit()
	return job


def make_sales_invoice(job, amount=1000, submit=True):
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": job.company,
			"customer": job.customer,
			"operations": job.name,
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"set_posting_time": 1,
			"items": [{"item_code": ITEM, "qty": 1, "rate": amount}],
		}
	)
	si.insert(ignore_permissions=True)
	if submit:
		si.submit()
	return si


def make_payment(si, amount):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry("Sales Invoice", si.name, party_amount=amount)
	pe.reference_no = "TEST"
	pe.reference_date = nowdate()
	# Both mandatory on the production copy (Property Setter / Custom Field).
	pe.mode_of_payment = frappe.db.get_value("Mode of Payment Account", {"company": si.company}, "parent")
	pe.type = "Test"
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def job_billing(job):
	return frappe.db.get_value("Operations", job.name, "billing_status")


class TestJob360(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Sites copied from production carry Server Scripts on Sales Invoice,
		# which raise when server scripts are disabled on the bench. They are
		# not what is under test here.
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_billing_status_transitions(self):
		job = make()
		self.assertEqual(job.billing_status, "No Invoice")

		draft = make_sales_invoice(job, submit=False)
		self.assertEqual(job_billing(job), "No Invoice", "a draft invoice does not bill the job")

		draft.submit()
		self.assertEqual(job_billing(job), "Invoiced")

		draft.reload()
		total = draft.grand_total
		first = make_payment(draft, total / 2)
		self.assertEqual(job_billing(job), "Partly Paid")

		second = make_payment(draft, total - total / 2)
		self.assertEqual(job_billing(job), "Paid")

		second.cancel()
		self.assertEqual(job_billing(job), "Partly Paid")
		first.cancel()
		self.assertEqual(job_billing(job), "Invoiced")

		draft.reload()
		draft.cancel()
		self.assertEqual(job_billing(job), "No Invoice")
		self.assertEqual(get_billing_status(job.name), "No Invoice")

	def test_banner_b1_documents_pending(self):
		job = make(
			document_table=[
				{"document": _first("Document List"), "received": "Yes"},
				{
					"document": _first("Document List", {"name": ["!=", _first("Document List")]}),
					"received": "",
				},
			]
		)
		payload = job_360.build(job.name)
		self.assertEqual((payload["kpis"]["docs_received"], payload["kpis"]["docs_total"]), (1, 2))
		b1 = [b for b in payload["banners"] if b["rule_code"] == "B1"]
		self.assertTrue(b1)
		self.assertIn("1 document awaiting", b1[0]["message"])

		job.reload()
		for row in job.document_table:
			row.received = "Yes"
		job.save()
		self.assertNotIn("B1", codes(job_360.build(job.name)))

	def test_banner_b2_cleared_by_record_actual(self):
		job = make(etd_date=add_days(nowdate(), -2), eta_date=add_days(nowdate(), 5))
		self.assertIn("B2", codes(job_360.get(job.name)))

		payload = job_360.record_actual(job.name, "atd", add_days(nowdate(), -1))
		self.assertNotIn("B2", codes(payload))
		self.assertEqual(payload["job"]["atd_date"], add_days(nowdate(), -1))
		self.assertEqual(
			str(frappe.db.get_value("Operations", job.name, "atd_date")), add_days(nowdate(), -1)
		)

	def test_record_actual_on_submitted_job_moves_free_time(self):
		job = make(eta_date=add_days(nowdate(), -3), free_time_days=5)
		submit_job(job)
		self.assertEqual(str(job.free_time_expiry), add_days(nowdate(), 2))

		payload = job_360.record_actual(job.name, "ata", nowdate())
		self.assertEqual(payload["job"]["ata_date"], nowdate())
		self.assertEqual(payload["job"]["free_time_expiry"], add_days(nowdate(), 5))
		self.assertNotIn("B3", codes(payload))

	def test_record_actual_rejects_other_fields(self):
		job = make()
		self.assertRaises(frappe.ValidationError, job_360.record_actual, job.name, "eta", nowdate())

	def test_banner_b7_customs_missing(self):
		# C8: Customs Clearance ticked and no Custom Clearance, whatever the job type.
		self.assertIn("B7", codes(job_360.build(make(job_type="Export", svc_customs_clearance=1).name)))
		self.assertNotIn("B7", codes(job_360.build(make(job_type="Import", svc_customs_clearance=0).name)))

	def test_b4_colour_follows_days_left(self):
		job = make(eta_date=add_days(nowdate(), -10), free_time_days=5)
		b4 = [b for b in job_360.build(job.name)["banners"] if b["rule_code"] == "B4"]
		self.assertEqual(b4[0]["colour"], "critical")

	def test_get_shape(self):
		job = make(
			mode_of_shipment="Sea",
			job_type="Export",
			container_details=[{"container_no": "TEST1234567", "size": "40"}, {"size": "20"}],
			cost_table=[{"item": ITEM, "cost": 300, "rate": 500}],
			cutoffs=[{"milestone": "Cargo Cut-off", "latest": add_to_date(now_datetime(), hours=-1)}],
		)
		make_sales_invoice(job, amount=1000)
		frappe.cache.delete_value(cache_key(job.name))

		payload = job_360.get(job.name)
		self.assertEqual(
			set(payload),
			{
				"job",
				"kpis",
				"banners",
				"linked",
				"units",
				"documents",
				"charges",
				"estimate",
				"milestones",
				"cutoffs",
				"invoices",
			},
		)
		self.assertEqual(
			set(payload["kpis"]),
			{
				"docs_received",
				"docs_total",
				"pending_documents",
				"linked_count",
				"cost_total",
				"revenue_total",
				"margin_pct",
				"billed",
				"collected",
				"free_days_left",
			},
		)
		self.assertEqual(set(payload["linked"]), {"transportation", "custom_clearance"})
		self.assertEqual(set(payload["invoices"]), {"sales", "purchase", "payments"})
		self.assertEqual(
			set(payload["job"]),
			{
				*job_360.JOB_FIELDS,
				"shipping_line_supplier",
				"carrier_supplier",
				"services",
				"service_types",
				"scopes_of_work",
				"allowed_service_types",
			},
		)

		kpis = payload["kpis"]
		self.assertEqual(kpis["cost_total"], 300)
		self.assertEqual(kpis["revenue_total"], 1000)
		self.assertEqual(kpis["margin_pct"], 70)
		self.assertEqual(payload["job"]["billing_status"], "Invoiced")

		self.assertEqual([u["attention"] for u in payload["units"]], [False, True])
		self.assertEqual(payload["cutoffs"][0]["cutoff_status"], "Passed")
		self.assertEqual(payload["charges"][0]["source_doctype"], "Operations")
		self.assertIn("billed", {m["key"] for m in payload["milestones"]})
		self.assertTrue(frappe.cache.get_value(cache_key(job.name)))

		job.reload()
		job.save()
		self.assertIsNone(frappe.cache.get_value(cache_key(job.name)), "saving the job drops its cache")

	def test_linked_transportation_documents_are_merged(self):
		job = make()
		transport = frappe.get_doc(
			{
				"doctype": "Transportation",
				"operations": job.name,
				"document_table": [{"document": _first("Document List"), "received": ""}],
			}
		).insert(ignore_permissions=True)

		payload = job_360.get(job.name)
		self.assertEqual(payload["kpis"]["linked_count"], 1)
		self.assertEqual(payload["linked"]["transportation"][0]["name"], transport.name)
		sources = {(d["source_doctype"], d["source_name"]) for d in payload["documents"]}
		self.assertIn(("Transportation", transport.name), sources)

	def test_cutoff_status(self):
		self.assertEqual(get_cutoff_status(add_to_date(now_datetime(), days=-1)), "Passed")
		self.assertEqual(get_cutoff_status(add_to_date(now_datetime(), days=3)), "Upcoming")
		self.assertIsNone(get_cutoff_status(None))

	def test_air_chargeable_weight(self):
		job = make(gross_weight=100, cbm=2)
		self.assertEqual(job.chargable_weight, 334)
		sea = make(mode_of_shipment="Sea", gross_weight=100, cbm=2, chargable_weight=50)
		self.assertEqual(sea.chargable_weight, 50)

	def test_conditions_registry_matches_rule_options(self):
		options = frappe.get_meta("Job Banner Rule").get_field("condition_key").options.split("\n")
		registered = set()
		for applies_to in ("Operations", "Customer", "Supplier"):
			registered |= set(banners.conditions_for(applies_to))
		self.assertEqual(set(filter(None, options)), registered)


def codes(payload):
	return {b["rule_code"] for b in payload["banners"]}
