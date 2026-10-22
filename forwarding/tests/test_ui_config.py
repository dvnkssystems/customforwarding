# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""forwarding.api.ui_config: page and wizard config read from custom_ui
records, with the built-in defaults as the fallback."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.api import ui_config
from forwarding.patches.v1_0 import seed_ui_config

TEST_USER = "ui-config-test@example.com"
TEST_ROLE = "_Test UI Config Role"


def keys(rows):
	return [r["key"] for r in rows]


def set_props(dashboard, mutate):
	doc = frappe.get_doc("Custom UI Dashboard", dashboard)
	props = json.loads(doc.entity_props)
	mutate(props)
	doc.entity_props = json.dumps(props)
	doc.save()
	return doc


class TestUIConfig(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# The seeded records are what the tests edit; make sure they exist
		# (the patch only inserts what is missing).
		seed_ui_config.execute()
		if not frappe.db.exists("Role", TEST_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE, "desk_access": 1}).insert()
		if not frappe.db.exists("User", TEST_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": TEST_USER,
					"first_name": "UI Config",
					"send_welcome_email": 0,
					"roles": [{"role": "Freight Viewer"}],
				}
			).insert()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("ui_config_test")
		ui_config.clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="ui_config_test")
		ui_config.clear_cache()

	# -- Pages ---------------------------------------------------------------------

	def test_seeded_pages_match_the_defaults(self):
		for page in ui_config.PAGES:
			got = ui_config.get_page(page)
			want = ui_config.default_page(page)
			self.assertEqual(got.pop("source"), "custom_ui", page)
			want.pop("source")
			self.assertEqual(got, want, page)

	def test_defaults_when_no_dashboard(self):
		for page in ui_config.PAGES:
			frappe.db.set_value("Custom UI Dashboard", ui_config.PAGES[page]["dashboard"], "is_active", 0)
		ui_config.clear_cache()
		for page in ui_config.PAGES:
			got = ui_config.get_page(page)
			self.assertEqual(got["source"], "default")
			self.assertEqual(got, ui_config.default_page(page))

	def test_unknown_page_is_refused(self):
		self.assertRaises(frappe.ValidationError, ui_config.get_page, "nope")

	def test_tabs_renamed_reordered_and_hidden(self):
		doc = frappe.get_doc("Custom UI Dashboard", "Job 360")
		by_key = {row.tab_key: row for row in doc.tabs}
		by_key["documents"].label = "Paperwork"
		by_key["documents"].icon = "folder"
		by_key["activity"].sort_order = 1
		by_key["overview"].is_default = 0
		by_key["invoices"].is_default = 1
		doc.remove(by_key["milestones"])
		doc.append("tabs", {"tab_group": "Entity", "tab_key": "bogus", "label": "Bogus", "sort_order": 2})
		doc.save()

		page = ui_config.get_page("job_360")
		self.assertEqual(
			keys(page["tabs"]), ["activity", "overview", "documents", "services", "charges", "invoices"]
		)
		tabs = {t["key"]: t for t in page["tabs"]}
		self.assertEqual(tabs["documents"]["label"], "Paperwork")
		self.assertEqual(tabs["documents"]["icon"], "folder")
		self.assertEqual([t["key"] for t in page["tabs"] if t["is_default"]], ["invoices"])
		# The free-time tile opened Milestones, which is now hidden.
		free_time = next(t for t in page["tiles"] if t["key"] == "free_time")
		self.assertIsNone(free_time["tab"])

	def test_non_entity_tab_rows_are_ignored(self):
		doc = frappe.get_doc("Custom UI Dashboard", "Customer 360")
		doc.append("tabs", {"tab_group": "Primary", "tab_key": "payments", "label": "Not me", "sort_order": 0})
		doc.save()
		page = ui_config.get_page("customer_360")
		self.assertEqual(next(t for t in page["tabs"] if t["key"] == "payments")["label"], "Payments")

	def test_tiles_renamed_reordered_hidden_and_unknown_dropped(self):
		def mutate(props):
			tiles = {t["key"]: t for t in props["tiles"]}
			tiles["payables"]["label"] = "Owed to them"
			tiles["documents"]["hidden"] = 1
			tiles["billed_year"]["tab"] = "jobs"
			props["tiles"] = [
				tiles["billed_year"],
				{"key": "mystery", "label": "Mystery"},
				tiles["payables"],
				tiles["active_jobs"],
				tiles["documents"],
				tiles["cost_variance"],
			]

		set_props("Supplier 360", mutate)
		tiles = ui_config.get_page("supplier_360")["tiles"]
		self.assertEqual(keys(tiles), ["billed_year", "payables", "active_jobs", "cost_variance"])
		self.assertEqual(tiles[1]["label"], "Owed to them")
		self.assertEqual(tiles[0]["tab"], "jobs")

	def test_actions_renamed_reordered_regrouped_and_hidden(self):
		def mutate(props):
			actions = {a["key"]: a for a in props["actions"]}
			actions["duplicate"]["group"] = None
			actions["duplicate"]["label"] = "Copy job"
			actions["record_atd"]["hidden"] = 1
			actions["print"]["group"] = "no_such_group"
			props["actions"] = [actions["duplicate"], {"key": "launch_rocket"}] + [
				a for k, a in actions.items() if k != "duplicate"
			]
			props["action_groups"] = [
				{"key": "more", "label": "Other"},
				{"key": "create", "label": "New"},
				{"key": "update", "label": "Update"},
				{"key": "print", "label": "Print / Send"},
				{"key": "teleport", "label": "Teleport"},
			]

		set_props("Job 360", mutate)
		page = ui_config.get_page("job_360")
		actions = {a["key"]: a for a in page["actions"]}
		self.assertEqual(page["actions"][0]["key"], "duplicate")
		self.assertEqual(actions["duplicate"]["label"], "Copy job")
		self.assertIsNone(actions["duplicate"]["group"])
		self.assertNotIn("record_atd", actions)
		self.assertNotIn("launch_rocket", actions)
		# An unknown group falls back to the action's own.
		self.assertEqual(actions["print"]["group"], "print")
		self.assertEqual(keys(page["groups"]), ["more", "create", "update", "print"])
		self.assertEqual(page["groups"][0]["label"], "Other")

	def test_group_with_no_actions_is_dropped(self):
		def mutate(props):
			for action in props["actions"]:
				if action["group"] == "print":
					action["hidden"] = 1

		set_props("Job 360", mutate)
		self.assertNotIn("print", keys(ui_config.get_page("job_360")["groups"]))

	def test_banner_limit(self):
		set_props("Customer 360", lambda props: props.update({"banners": {"max_visible": 5}}))
		self.assertEqual(ui_config.get_page("customer_360")["banners"], {"max_visible": 5})
		set_props("Customer 360", lambda props: props.update({"banners": {"max_visible": "lots"}}))
		self.assertEqual(ui_config.get_page("customer_360")["banners"], {"max_visible": 3})

	def test_home_sections(self):
		def mutate(props):
			sections = {s["key"]: s for s in props["sections"]}
			sections["checklist"]["hidden"] = 1
			sections["modules"]["label"] = "Apps"
			props["sections"] = [
				sections["billing_pipeline"],
				sections["modules"],
				{"key": "weather", "label": "Weather"},
				sections["kpis"],
				sections["checklist"],
				sections["worklist"],
			]

		set_props("Freight Home", mutate)
		sections = ui_config.get_page("home")["sections"]
		self.assertEqual(keys(sections), ["billing_pipeline", "modules", "kpis", "worklist"])
		self.assertEqual(sections[1]["label"], "Apps")

	def test_bad_json_falls_back_to_defaults(self):
		# custom_ui refuses it on save ...
		doc = frappe.get_doc("Custom UI Dashboard", "Job 360")
		doc.entity_props = "{not json"
		self.assertRaises(frappe.ValidationError, doc.save)
		# ... but a record written around validation must not break the page.
		frappe.db.set_value("Custom UI Dashboard", "Job 360", "entity_props", "{not json")
		ui_config.clear_cache()
		page = ui_config.get_page("job_360")
		self.assertEqual(page["source"], "default")
		self.assertEqual(page, ui_config.default_page("job_360"))

	def test_wrongly_shaped_parts_use_their_defaults(self):
		set_props("Supplier 360", lambda props: props.update({"tiles": "five tiles", "actions": {"edit": 1}}))
		page = ui_config.get_page("supplier_360")
		self.assertEqual(page["source"], "custom_ui")
		default = ui_config.default_page("supplier_360")
		self.assertEqual(page["tiles"], default["tiles"])
		self.assertEqual(page["actions"], default["actions"])

	def test_roles_gate_the_dashboard(self):
		doc = frappe.get_doc("Custom UI Dashboard", "Customer 360")
		doc.append("roles", {"role": TEST_ROLE})
		doc.tabs[0].label = "Shipments"
		doc.save()

		self.assertEqual(ui_config.get_page("customer_360")["tabs"][0]["label"], "Shipments")
		frappe.set_user(TEST_USER)
		page = ui_config.get_page("customer_360")
		self.assertEqual(page["source"], "default")
		self.assertEqual(page["tabs"][0]["label"], "Jobs")

	def test_saving_the_dashboard_clears_the_cache(self):
		self.assertEqual(ui_config.get_page("job_360")["tabs"][0]["label"], "Overview")
		doc = frappe.get_doc("Custom UI Dashboard", "Job 360")
		doc.tabs[0].label = "Summary"
		doc.save()
		self.assertEqual(ui_config.get_page("job_360")["tabs"][0]["label"], "Summary")

	def test_guest_is_refused(self):
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, ui_config.get_page, "home")
		self.assertRaises(frappe.PermissionError, ui_config.get_wizard)

	# -- Wizard --------------------------------------------------------------------

	def test_seeded_wizard_matches_the_defaults(self):
		got = ui_config.get_wizard()
		want = ui_config.default_wizard("New Job")
		self.assertEqual(got.pop("source"), "custom_ui")
		want.pop("source")
		self.assertEqual(got, want)
		basics = got["steps"][0]
		self.assertEqual(
			next(f for f in basics["fields"] if f["fieldname"] == "activity_code")["label"], "Service Type"
		)

	def test_wizard_defaults_without_a_layout(self):
		frappe.db.set_value("Custom UI Wizard Layout", "New Job", "is_active", 0)
		ui_config.clear_cache()
		wizard = ui_config.get_wizard()
		self.assertEqual(wizard["source"], "default")
		self.assertEqual(keys(wizard["steps"]), ["basics", "parties", "route", "cargo"])

	def test_wizard_reflects_field_edits(self):
		ui_config.get_wizard()  # warm the cache: the save must drop it
		layout = frappe.get_doc("Custom UI Wizard Layout", "New Job")
		rows = {(r.section, r.fieldname): r for r in layout.fields}
		rows[("parties", "consignee")].label = "Receiver"
		rows[("parties", "shipper")].hidden = 1
		rows[("parties", "po_no")].read_only = 1
		layout.remove(rows[("cargo", "cbm")])
		rows[("parties", "salesman")].idx = 0  # first in its step
		layout.fields.sort(key=lambda r: r.idx)
		for i, row in enumerate(layout.fields, 1):
			row.idx = i
		settings = json.loads(layout.description)
		settings["save_from_step"] = 2
		settings["steps"][3]["label"] = "Goods"
		settings["steps"].append({"key": "payment", "label": "Payment"})
		layout.description = json.dumps(settings)
		layout.save()

		wizard = ui_config.get_wizard()
		self.assertEqual(wizard["save_from_step"], 2)
		self.assertEqual(keys(wizard["steps"]), ["basics", "parties", "route", "cargo"])
		self.assertEqual(wizard["steps"][3]["label"], "Goods")
		parties = {f["fieldname"]: f for f in wizard["steps"][1]["fields"]}
		self.assertEqual(wizard["steps"][1]["fields"][0]["fieldname"], "salesman")
		self.assertEqual(parties["consignee"]["label"], "Receiver")
		self.assertEqual(parties["shipper"]["hidden"], 1)
		self.assertEqual(parties["po_no"]["read_only"], 1)
		self.assertNotIn("cbm", [f["fieldname"] for f in wizard["steps"][3]["fields"]])

	def test_wizard_bad_description_keeps_default_steps(self):
		frappe.db.set_value("Custom UI Wizard Layout", "New Job", "description", "Steps for a new job")
		ui_config.clear_cache()
		wizard = ui_config.get_wizard()
		self.assertEqual(wizard["source"], "custom_ui")
		self.assertEqual(wizard["save_from_step"], 1)
		self.assertEqual(wizard["steps"][0]["label"], "Basics")

	def test_mandatory_field_cannot_be_hidden(self):
		layout = frappe.get_doc("Custom UI Wizard Layout", "New Job")
		customer = next(r for r in layout.fields if r.fieldname == "customer")
		customer.hidden = 1
		self.assertRaises(frappe.ValidationError, layout.save)

		# Even written around validation, the wizard still shows it.
		frappe.db.set_value("Custom UI Wizard Field", customer.name, "hidden", 1)
		ui_config.clear_cache()
		parties = {f["fieldname"]: f for f in ui_config.get_wizard()["steps"][1]["fields"]}
		self.assertEqual(parties["customer"]["hidden"], 0)
