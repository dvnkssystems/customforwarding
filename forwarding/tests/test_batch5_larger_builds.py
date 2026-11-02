# Copyright (c) 2026, DVNKS Systems and contributors
"""Batch 5 (larger builds): Simran's Round 3 Addendum items A-31, A-40, A-41,
A-46 and A-47 — the backend halves. A-39 and A-42, and the app's side of
the rest, are checked in the app's tests/store.spec.js."""

import base64
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.api import bug_report, bulk
from forwarding.party_documents import EXPIRED, EXPIRING, VALID
from forwarding.patches.v1_0 import b5_fleet_banner_documents, b5_sidebar_cleanup
from forwarding.patches.v1_0 import seed_fleet_banner_rules as seed
from forwarding.tests.test_supplier_360 import codes, fresh, make_supplier
from forwarding.tests.test_supplier_fleet import banner, in_days

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PLAIN_USER = "batch5-plain@example.com"


def plain_user():
	"""A signed-in user with no roles."""
	if not frappe.db.exists("User", PLAIN_USER):
		frappe.get_doc(
			{"doctype": "User", "email": PLAIN_USER, "first_name": "Plain", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return PLAIN_USER


def make_truck(transporter, **dates):
	"""A vehicle with only what the transporter's fleet needs (A-31)."""
	return frappe.get_doc(
		{
			"doctype": "Vehicle",
			"license_plate": dates.pop("plate", None) or f"B5-{frappe.generate_hash(length=6)}",
			"make": "Volvo",
			"model": "FH",
			"transporter": transporter,
			**dates,
		}
	).insert(ignore_permissions=True)


class TestVehicleForm(IntegrationTestCase):
	# A-31: Vehicle Type, Istimara and Fahas dates; the company-car fields go.

	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_fields(self):
		meta = frappe.get_meta("Vehicle")
		self.assertEqual(
			meta.get_field("vehicle_type").options.split("\n")[1:],
			["Flatbed", "Lowbed", "Curtain-side", "Reefer", "Tanker", "Box"],
		)
		self.assertEqual(meta.get_field("registration_expiry").fieldtype, "Date")
		self.assertEqual(meta.get_field("inspection_expiry").fieldtype, "Date")
		for fieldname in ("last_odometer", "fuel_type", "uom"):
			self.assertFalse(meta.get_field(fieldname).reqd, fieldname)
		for fieldname in ("last_odometer", "fuel_type", "uom", "carbon_check_date", "wheels", "doors"):
			self.assertTrue(meta.get_field(fieldname).hidden, fieldname)
		# Make and Model stay required: the fleet tab lists them.
		self.assertTrue(meta.get_field("make").reqd)
		self.assertTrue(meta.get_field("model").reqd)

	def test_saves_without_odometer_or_fuel(self):
		vehicle = make_truck(make_supplier(is_transporter=1).name, vehicle_type="Reefer")
		self.assertEqual(frappe.db.get_value("Vehicle", vehicle.name, "vehicle_type"), "Reefer")

	def test_soonest_document_sets_the_status(self):
		supplier = make_supplier(is_transporter=1).name
		truck = make_truck(
			supplier,
			start_date=in_days(-300),
			end_date=in_days(200),
			registration_expiry=in_days(5),
			inspection_expiry=in_days(90),
		)
		(row,) = fresh(supplier)["vehicles"]
		self.assertEqual(row["name"], truck.name)
		self.assertEqual((row["expiry_document"], row["expiry_status"], row["days_left"]), ("registration (Istimara)", EXPIRING, 5))
		self.assertEqual([d["status"] for d in row["documents"]], [EXPIRING, VALID, VALID])

	def test_registration_expiring_raises_s5(self):
		supplier = make_supplier(is_transporter=1).name
		make_truck(supplier, plate="REG-55", registration_expiry=in_days(7))
		payload = fresh(supplier)
		self.assertIn("Vehicle REG-55 registration (Istimara) expires", banner(payload, "S5")["message"])
		self.assertNotIn("S9", codes(payload))

	def test_inspection_expired_raises_s9(self):
		supplier = make_supplier(is_transporter=1).name
		make_truck(supplier, plate="FAH-9", inspection_expiry=in_days(-2))
		payload = fresh(supplier)
		self.assertIn("Vehicle FAH-9 inspection (Fahas) expired", banner(payload, "S9")["message"])

	def test_each_document_counts_in_the_banner(self):
		supplier = make_supplier(is_transporter=1).name
		make_truck(supplier, start_date=in_days(-300), end_date=in_days(3), registration_expiry=in_days(4))
		payload = fresh(supplier)
		self.assertTrue(banner(payload, "S5")["message"].startswith("2 vehicle / driver documents expire"))

	def test_banner_patch_keeps_an_edited_rule(self):
		for code in ("S5", "S9"):
			original = frappe.db.get_value("Job Banner Rule", code, "message_template")
			self.addCleanup(frappe.db.set_value, "Job Banner Rule", code, "message_template", original)
		self.assertNotEqual(b5_fleet_banner_documents.as_seeded(seed.EXPIRING, "expires"), seed.EXPIRING)
		old = b5_fleet_banner_documents.as_seeded(seed.EXPIRING, "expires")
		frappe.db.set_value("Job Banner Rule", "S5", "message_template", old)
		frappe.db.set_value("Job Banner Rule", "S9", "message_template", "Edited on site")
		b5_fleet_banner_documents.execute()
		self.assertEqual(frappe.db.get_value("Job Banner Rule", "S5", "message_template"), seed.EXPIRING)
		self.assertEqual(frappe.db.get_value("Job Banner Rule", "S9", "message_template"), "Edited on site")


def make_waybill(**values):
	return frappe.get_doc({"doctype": "Freight Waybill", "waybill_type": "Import", **values}).insert(
		ignore_permissions=True
	)


class TestBulkActions(IntegrationTestCase):
	# A-40: per-row outcomes, permission-aware.

	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_permissions_for_a_submittable_doctype(self):
		out = bulk.permissions("Freight Waybill")
		self.assertTrue(out["is_submittable"])
		self.assertTrue(all(out["perms"][p] for p in ("read", "write", "delete", "submit", "cancel")))
		fields = {f["fieldname"]: f for f in out["fields"]}
		self.assertIn("shipper", fields)
		self.assertEqual(fields["waybill_type"]["options"], "Import\nExport\nLocal Freight")
		# Not typed into from a list: tables, editors, read-only and hidden.
		self.assertFalse({"container_items", "terms_text", "approved_by", "public_token"} & set(fields))

	def test_not_submittable_has_no_submit_or_cancel(self):
		out = bulk.permissions("ToDo")
		self.assertFalse(out["is_submittable"])
		self.assertFalse(out["perms"]["submit"] or out["perms"]["cancel"])

	def test_a_user_who_cannot_read_is_refused(self):
		frappe.set_user(plain_user())
		with self.assertRaises(frappe.PermissionError):
			bulk.permissions("Freight Waybill")

	def test_submit_reports_each_row(self):
		draft = make_waybill()
		submitted = make_waybill()
		submitted.submit()
		out = bulk.run("Freight Waybill", [draft.name, submitted.name], "submit")
		self.assertEqual(out["done"], [draft.name])
		self.assertEqual(out["failed"], [{"name": submitted.name, "error": "Only a draft can be submitted"}])
		self.assertEqual(frappe.db.get_value("Freight Waybill", draft.name, "docstatus"), 1)

	def test_cancel_and_delete(self):
		a, b = make_waybill(), make_waybill()
		a.submit()
		self.assertEqual(bulk.run("Freight Waybill", [a.name], "cancel")["done"], [a.name])
		self.assertEqual(frappe.db.get_value("Freight Waybill", a.name, "docstatus"), 2)
		self.assertEqual(bulk.run("Freight Waybill", [b.name], "delete")["done"], [b.name])
		self.assertFalse(frappe.db.exists("Freight Waybill", b.name))

	def test_set_field_rolls_back_only_the_failed_row(self):
		a, b = make_waybill(), make_waybill()
		frappe.db.set_value("Freight Waybill", b.name, "docstatus", 2)
		out = bulk.run("Freight Waybill", [a.name, b.name], "set", fieldname="shipper", value="ACME")
		self.assertEqual(out["done"], [a.name])
		self.assertEqual(out["failed"][0]["error"], "A cancelled record cannot be changed")
		self.assertEqual(frappe.db.get_value("Freight Waybill", a.name, "shipper"), "ACME")
		bad = bulk.run("Freight Waybill", [a.name], "set", fieldname="supplier", value="No Such Supplier B5")
		self.assertEqual(bad["done"], [])
		self.assertIn("No Such Supplier B5", bad["failed"][0]["error"])

	def test_guards(self):
		w = make_waybill()
		with self.assertRaises(frappe.ValidationError):
			bulk.run("Freight Waybill", [w.name], "set", fieldname="approved_by", value="Administrator")
		with self.assertRaises(frappe.ValidationError):
			bulk.run("ToDo", ["x"], "submit")
		with self.assertRaises(frappe.ValidationError):
			bulk.run("Freight Waybill", [str(i) for i in range(bulk.MAX_ROWS + 1)], "delete")
		with self.assertRaises(frappe.ValidationError):
			bulk.run("Freight Waybill", [w.name], "rename")

	def test_a_user_without_rights_gets_a_reason_per_row(self):
		w = make_waybill()
		frappe.set_user(plain_user())
		out = bulk.run("Freight Waybill", [w.name], "delete")
		self.assertEqual(out["done"], [])
		self.assertTrue(out["failed"][0]["error"])
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Freight Waybill", w.name))


class TestReportTotals(IntegrationTestCase):
	# A-41: a Total row on Operations & Invoice Details; one on Estimated Job Summary.

	def test_operations_and_invoice_details_has_a_total_row(self):
		self.assertEqual(frappe.db.get_value("Report", "Operations and Invoice Details", "add_total_row"), 1)

	def test_estimated_summary_appends_one_total(self):
		try:
			import pandas  # noqa: F401
		except ImportError:
			self.skipTest("pandas is not installed on this bench")
		from forwarding.forwarding.report.estimated_job_report_summary import estimated_job_report_summary as rpt

		jobs = [frappe._dict(operations="J1", date="2026-10-01"), frappe._dict(operations="J2", date="2026-10-02")]
		cost = {
			"J1": [{"item": "A", "account": "X", "cost": 10, "rate": 15, "paid_amount": 0, "pending_amount": 10, "received_amount": 0, "pending_amount_to_receive": 15}],
			"J2": [{"item": "B", "account": "X", "cost": 20, "rate": 30, "paid_amount": 0, "pending_amount": 20, "received_amount": 0, "pending_amount_to_receive": 30}],
		}
		with patch.object(rpt, "get_data", return_value=jobs), patch.object(
			rpt, "get_cost_table_details", side_effect=lambda job: cost[job]
		):
			_columns, data = rpt.execute({})
		totals = [r for r in data if "Total" in str(r.get("customer") or "")]
		self.assertEqual(len(totals), 1)
		self.assertIs(totals[0], data[-1])
		self.assertEqual((totals[0]["cost"], totals[0]["rate"]), (30, 45))


class TestSidebarCleanup(IntegrationTestCase):
	# A-46: menu entries only.

	def item(self, label, item_type="Link", parent=None, **values):
		return frappe.get_doc(
			{
				"doctype": "Custom UI Sidebar Item",
				"name": f"B5 {label} {frappe.generate_hash(length=5)}",
				"item_label": label,
				"item_type": item_type,
				"parent_item": parent,
				"is_active": 1,
				**values,
			}
		).insert(ignore_permissions=True)

	def test_entries(self):
		if not frappe.db.exists("DocType", "Custom UI Sidebar Item"):
			self.skipTest("custom_ui is not installed")
		transport = self.item("B5 Transport", item_type="Group")
		dunning = self.item("Dunning (Collections)", parent=transport.name, target_doctype="Dunning")
		seaports = self.item("Seaports", parent=transport.name, target_doctype="Freight Seaport")
		lorry = self.item("Lorry Receipt", parent=transport.name, target_doctype="Sales Order")
		orders = self.item("Sales Orders", parent=transport.name, target_doctype="Sales Order")
		customers = self.item("Customers", parent=transport.name, target_doctype="Customer")
		b5_sidebar_cleanup.execute()
		active = lambda d: frappe.db.get_value("Custom UI Sidebar Item", d.name, "is_active")  # noqa: E731
		self.assertEqual([active(d) for d in (dunning, seaports, lorry, orders)], [0, 0, 0, 1])
		parties = b5_sidebar_cleanup.top_group("Parties")
		if parties:
			self.assertEqual(frappe.db.get_value("Custom UI Sidebar Item", customers.name, "parent_item"), parties)
		# Nothing is deleted.
		self.assertTrue(frappe.db.exists("Custom UI Sidebar Item", dunning.name))


class TestBugReport(IntegrationTestCase):
	# A-47: always saved; a GitHub issue only when configured, never under test.

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def send(self, **kw):
		args = {"subject": "Save button greyed", "message": "Clicked Save on /jobs/X", "page": "/jobs/JOB-1"}
		args.update(kw)
		return bug_report.submit(**args)

	def test_saved_without_config(self):
		with patch.dict(frappe.conf, {"github_bug_repo": None, "github_bug_token": None}):
			out = self.send(image=base64.b64encode(PNG).decode(), image_name="shot one.png")
		self.assertEqual(out["github"], "not_configured")
		doc = frappe.get_doc("App Bug Report", out["name"])
		self.assertEqual((doc.reported_by, doc.page, doc.github_status), ("Administrator", "/jobs/JOB-1", "Not Configured"))
		file = frappe.get_doc("File", {"file_url": doc.image})
		self.assertTrue(file.is_private)
		self.assertEqual((file.attached_to_doctype, file.attached_to_name), ("App Bug Report", doc.name))
		self.assertEqual(file.file_name, "shot-one.png")

	def test_data_url_accepted(self):
		out = self.send(image="data:image/png;base64," + base64.b64encode(PNG).decode(), image_name="a.png")
		self.assertTrue(frappe.db.get_value("App Bug Report", out["name"], "image"))

	def test_input_checks(self):
		for kw in (
			{"subject": ""},
			{"message": "  "},
			{"subject": "x" * 141},
			{"message": "x" * 5001},
			{"image": base64.b64encode(b"not an image").decode(), "image_name": "a.png"},
			{"image": base64.b64encode(PNG).decode(), "image_name": "a.exe"},
			{"image": "%%%", "image_name": "a.png"},
		):
			with self.assertRaises(frappe.ValidationError, msg=str(kw)[:60]):
				self.send(**kw)

	def test_rate_limited(self):
		with patch("frappe.db.count", return_value=bug_report.MAX_PER_HOUR):
			with self.assertRaises(frappe.ValidationError):
				self.send()

	def test_guest_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			self.send()

	def test_any_user_may_report(self):
		frappe.set_user(plain_user())
		out = self.send()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("App Bug Report", out["name"], "reported_by"), PLAIN_USER)

	def test_configured_queues_but_never_calls_out_under_test(self):
		config = {"github_bug_repo": "dvnkssystems/freight_lcs_vue", "github_bug_token": "test-token"}
		with patch.dict(frappe.conf, config), patch("frappe.enqueue") as enqueue, patch("requests.post") as post:
			out = self.send()
			bug_report.create_github_issue(out["name"])
		self.assertEqual(out["github"], "queued")
		self.assertEqual(frappe.db.get_value("App Bug Report", out["name"], "github_status"), "Queued")
		enqueue.assert_not_called()
		post.assert_not_called()

	def test_bad_repo_is_not_configured(self):
		with patch.dict(frappe.conf, {"github_bug_repo": "not a repo", "github_bug_token": "t"}):
			self.assertEqual(self.send()["github"], "not_configured")

	def test_push_creates_the_issue(self):
		out = self.send(image=base64.b64encode(PNG).decode(), image_name="s.png", message="Ping @someone")
		response = MagicMock(status_code=201)
		response.json.return_value = {"html_url": "https://github.com/dvnkssystems/freight_lcs_vue/issues/7"}
		config = {"github_bug_repo": "dvnkssystems/freight_lcs_vue", "github_bug_token": "test-token"}
		with patch.dict(frappe.conf, config), patch("forwarding.api.bug_report.requests.post", return_value=response) as post:
			bug_report.push_to_github(out["name"])
		url, kwargs = post.call_args[0][0], post.call_args[1]
		self.assertEqual(url, "https://api.github.com/repos/dvnkssystems/freight_lcs_vue/issues")
		self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
		self.assertEqual(kwargs["timeout"], bug_report.TIMEOUT)
		body = kwargs["json"]["body"]
		self.assertEqual(kwargs["json"]["title"], "[App] Save button greyed")
		self.assertIn("/jobs/JOB-1", body)
		self.assertIn("Administrator", body)
		self.assertIn(frappe.db.get_value("App Bug Report", out["name"], "image"), body)
		self.assertNotIn("@someone", body)
		doc = frappe.get_doc("App Bug Report", out["name"])
		self.assertEqual((doc.github_status, doc.github_issue_url), ("Created", response.json.return_value["html_url"]))

	def test_push_failure_is_recorded(self):
		out = self.send()
		response = MagicMock(status_code=404)
		response.json.return_value = {"message": "Not Found"}
		config = {"github_bug_repo": "dvnkssystems/freight_lcs_vue", "github_bug_token": "test-token"}
		with patch.dict(frappe.conf, config), patch("forwarding.api.bug_report.requests.post", return_value=response):
			bug_report.push_to_github(out["name"])
		doc = frappe.get_doc("App Bug Report", out["name"])
		self.assertEqual((doc.github_status, doc.github_error), ("Failed", "GitHub 404: Not Found"))
		self.assertNotIn("test-token", doc.github_error)
