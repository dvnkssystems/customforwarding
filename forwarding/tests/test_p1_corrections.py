# Copyright (c) 2026, DVNKS Systems and contributors
"""The backend P1 items of the Phase 1 corrections review.

C5 / C6 package rows and header cargo, C7 charge sources, C8 banner B7,
C10 export cut-offs, C11 document checklist, C12 Job created milestone,
C16 document dates, C20-C22 prints, C26 Service Type filter, C27 ports,
C28 wizard Cargo fields. Uses the site's own masters; everything is rolled
back.
"""

import json
import re
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from forwarding.api import job_360, ui_config
from forwarding.forwarding.doctype.operations.operations import make_transportaion
from forwarding.patches.v1_0 import add_wizard_cargo_fields
from forwarding.tests.test_job_360 import ITEM, make
from forwarding.tests.test_job_360_p2 import _documents, job_with_rows, make_clearance, make_transportation

# The package rows of R-IM-A-26-07014: 7,055 kg chargeable in all.
PACKAGES_07014 = [
	{"length": 91, "width": 63, "height": 58, "weight": 399, "quantity": 5, "package_type": "Box"},
	{"length": 51, "width": 88, "height": 36, "weight": 347.2, "quantity": 5, "package_type": "Box"},
	{"length": 94, "width": 78, "height": 38, "weight": 166.2, "quantity": 20, "package_type": "Box"},
]


def _text(html):
	return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _port(code, name, mode="Sea", country="Saudi Arabia"):
	doc = frappe.get_doc(
		{"doctype": "Port", "port_code": code, "port_name": name, "mode_of_shipment": mode, "country": country}
	)
	return doc.insert(ignore_permissions=True, ignore_if_duplicate=True).name


class P1TestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		frappe.cache.delete_keys("job_360")


class TestPackages(P1TestCase):
	# C5 ------------------------------------------------------------------------

	def test_row_and_total_chargeable_weight(self):
		job = make(package_details=PACKAGES_07014)
		self.assertEqual([r.chargeable_weight for r in job.package_details], [1995, 1736, 3324])
		self.assertEqual(job.total_chargeable_weight, 7055)

	def test_volumetric_weight_wins_for_light_bulky_rows(self):
		# 2 x 1 m3 = 2 m3 -> 334 kg volumetric against 20 kg actual.
		job = make(package_details=[{"length": 100, "width": 100, "height": 100, "weight": 10, "quantity": 2}])
		row = job.package_details[0]
		self.assertAlmostEqual(row.volume, 2)
		self.assertAlmostEqual(row.chargeable_weight, 334)

	# C6 ------------------------------------------------------------------------

	def test_header_follows_package_rows(self):
		job = make(packages="294 PKGS", gross_weight=6645.5, cbm=29, chargable_weight=6645.5, package_details=PACKAGES_07014)
		self.assertEqual(job.packages, "30")
		self.assertEqual(job.no_of_pieces, 30)
		self.assertEqual(job.gross_weight, 7055)
		self.assertAlmostEqual(job.cbm, 8.043, places=3)
		self.assertEqual(job.chargable_weight, 7055)

	def test_header_kept_without_package_rows(self):
		job = make(mode_of_shipment="Sea", packages="12 PLT", gross_weight=900, cbm=4.5)
		self.assertEqual((job.packages, job.gross_weight, job.cbm), ("12 PLT", 900, 4.5))

	def test_header_fields_read_only_with_rows(self):
		meta = frappe.get_meta("Operations")
		for fieldname in ("packages", "gross_weight", "cbm", "chargable_weight", "no_of_pieces"):
			self.assertIn("package_details", meta.get_field(fieldname).read_only_depends_on or "", fieldname)
		self.assertEqual(meta.get_field("cbm").fieldtype, "Float")


class TestCharges(P1TestCase):
	# C7 ------------------------------------------------------------------------

	def test_cost_from_transportation_names_it_and_counts_once(self):
		job = make()
		tt = make_transportation(job, cost_table=[{"item": ITEM, "cost": 1000}])
		tt.reload()
		self.assertTrue(tt.cost_table[0].ref_id, "ref_id sticks on the first save")

		payload = job_360.build(job.name)
		self.assertEqual(len(payload["charges"]), 1)
		charge = payload["charges"][0]
		self.assertEqual((charge["source_doctype"], charge["source_name"]), ("Transportation", tt.name))
		self.assertEqual(charge["row_name"], tt.cost_table[0].name)
		self.assertEqual(charge["job_row_name"], tt.cost_table[0].ref_id)
		self.assertEqual(payload["kpis"]["cost_total"], 1000)

	def test_resaving_updates_the_job_copy(self):
		job = make()
		tt = make_transportation(job, cost_table=[{"item": ITEM, "cost": 1000}])
		tt.reload()
		tt.cost_table[0].cost = 1200
		tt.save()
		tt.save()  # used to raise: update_cost_table_in_operations did not exist
		self.assertEqual(frappe.db.get_value("Cost Table", tt.cost_table[0].ref_id, "cost"), 1200)
		self.assertEqual(job_360.build(job.name)["kpis"]["cost_total"], 1200)

	def test_cost_from_clearance(self):
		job = make()
		cc = make_clearance(job, cost_table=[{"item": ITEM, "cost": 400}])
		charges = job_360.build(job.name)["charges"]
		self.assertEqual([(c["source_doctype"], c["source_name"], c["cost"]) for c in charges], [("Custom Clearance", cc.name, 400)])

	def test_job_rows_copied_onto_a_transportation_stay_the_jobs(self):
		job = make(cost_table=[{"item": ITEM, "cost": 300}])
		tt = make_transportaion(job.name)
		tt.insert(ignore_permissions=True)
		payload = job_360.build(job.name)
		self.assertEqual([(c["source_doctype"], c["cost"]) for c in payload["charges"]], [("Operations", 300)])
		self.assertEqual(payload["kpis"]["cost_total"], 300)


class TestBannerB7(P1TestCase):
	# C8 ------------------------------------------------------------------------

	def codes(self, job):
		return {b["rule_code"] for b in job_360.build(job.name)["banners"]}

	def test_fires_only_when_customs_is_ticked(self):
		self.assertNotIn("B7", self.codes(make(job_type="Import", svc_customs_clearance=0)))
		self.assertIn("B7", self.codes(make(job_type="Import", svc_customs_clearance=1)))

	def test_cleared_by_a_custom_clearance(self):
		job = make(svc_customs_clearance=1)
		make_clearance(job)
		self.assertNotIn("B7", self.codes(job))


class TestCutoffs(P1TestCase):
	# C10 -----------------------------------------------------------------------

	def milestones(self, job):
		return [r.milestone for r in job.cutoffs]

	def test_sea_export(self):
		job = make(job_type="Export", mode_of_shipment="Sea", destination_country="Saudi Arabia")
		self.assertEqual(
			self.milestones(job), ["SI Deadline", "VGM Cut-off", "Cargo Cut-off", "Container Pickup"]
		)
		self.assertTrue(all(not r.deadline and not r.cutoff_status for r in job.cutoffs))

	def test_sea_export_to_the_united_states_adds_aes(self):
		job = make(job_type="Export", mode_of_shipment="Sea", destination_country="United States")
		self.assertIn("AES Deadline", self.milestones(job))

	def test_air_export(self):
		job = make(job_type="Export", mode_of_shipment="Air")
		self.assertEqual(self.milestones(job), ["SI Deadline", "Cargo Cut-off"])

	def test_import_and_given_rows_are_left_alone(self):
		self.assertEqual(self.milestones(make(job_type="Import", mode_of_shipment="Sea")), [])
		job = make(job_type="Export", mode_of_shipment="Sea", cutoffs=[{"milestone": "Cargo Cut-off"}])
		self.assertEqual(self.milestones(job), ["Cargo Cut-off"])

	def test_undated_rows_save_and_show_no_status(self):
		job = make(job_type="Export", mode_of_shipment="Air")
		job.save()
		self.assertEqual([c["cutoff_status"] for c in job_360.build(job.name)["cutoffs"]], [None, None])
		self.assertEqual(job_360.default_cutoffs("Air"), ["SI Deadline", "Cargo Cut-off"])


class TestDocumentChecklist(P1TestCase):
	# C11 -----------------------------------------------------------------------

	def shipment_type(self, docs):
		return frappe.get_doc(
			{
				"doctype": "Shipment Type",
				"shipment_type": f"P1 Test Air Type {frappe.generate_hash(length=6)}",
				"mode_of_shipment": "Air",
				"document_table": [
					{"document": docs[0], "stage": "Documentation", "received": "Yes", "date": nowdate()},
					{"document": docs[1], "stage": "Customs Clearance"},
				],
			}
		).insert(ignore_permissions=True)

	def test_new_job_gets_the_shipment_types_documents(self):
		docs = _documents()
		st = self.shipment_type(docs)
		job = make(shipment_type=st.name)
		rows = [(r.document, r.stage, r.received, r.date) for r in job.document_table]
		self.assertEqual(
			rows, [(docs[0], "Documentation", "No", None), (docs[1], "Customs Clearance", "No", None)]
		)

	def test_listed_documents_are_not_added_twice(self):
		docs = _documents()
		st = self.shipment_type(docs)
		job = make(
			shipment_type=st.name, document_table=[{"document": docs[0], "stage": "Documentation", "received": "Yes"}]
		)
		self.assertEqual([r.document for r in job.document_table], [docs[0], docs[1]])
		self.assertEqual(job.document_table[0].received, "Yes")

	def test_no_configured_documents_means_no_rows(self):
		self.assertEqual(make().document_table, [])


class TestMilestones(P1TestCase):
	# C12 -----------------------------------------------------------------------

	def test_job_created_is_the_job_date(self):
		job = make(date=add_days(nowdate(), -9))
		created = job_360.build(job.name)["milestones"][0]
		self.assertEqual(created["key"], "created")
		self.assertEqual(getdate(created["actual"]), getdate(add_days(nowdate(), -9)))


class TestDocumentDates(P1TestCase):
	# C16 -----------------------------------------------------------------------

	def test_date_only_once_received(self):
		job = job_with_rows()
		pending = next(r for r in job.document_table if r.received == "No")
		pending.date = nowdate()
		job.save()
		self.assertIsNone(next(r for r in job.document_table if r.name == pending.name).date)

		pending = next(r for r in job.document_table if r.name == pending.name)
		pending.received = "Yes"
		job.save()
		self.assertEqual(str(next(r for r in job.document_table if r.name == pending.name).date), nowdate())

	def test_copies_carry_no_date_unless_received(self):
		job = job_with_rows()
		for row in job.document_table:
			frappe.db.set_value("Document Table", row.name, "date", nowdate())
		received = {r.document for r in job.document_table if r.received == "Yes"}

		tt = make_transportation(job)
		tt.reload()
		self.assertEqual(len(tt.document_table), 3)
		for row in tt.document_table:
			self.assertEqual(bool(row.date), row.document in received, row.document)

		mapped = make_transportaion(job.name)
		for row in mapped.document_table:
			self.assertEqual(bool(row.date), row.document in received, row.document)


class TestPrints(P1TestCase):
	# C20 / C21 / C22 -----------------------------------------------------------

	def test_arrival_notice_after_ata_on_air(self):
		job = make(
			mode_of_shipment="Air",
			eta_date=add_days(nowdate(), -3),
			ata_date=add_days(nowdate(), -2),
			free_time_days=5,
		)
		text = _text(frappe.get_print("Operations", job.name, "Arrival Notice"))
		self.assertIn("arrived on", text)
		self.assertNotIn("expected to arrive", text)
		self.assertIn("Storage charges apply after", text)
		self.assertNotIn("demurrage", text)

	def test_arrival_notice_before_ata_on_sea(self):
		job = make(mode_of_shipment="Sea", eta_date=add_days(nowdate(), 3), free_time_days=5)
		text = _text(frappe.get_print("Operations", job.name, "Arrival Notice"))
		self.assertIn("expected to arrive", text)
		self.assertIn("demurrage and detention", text)
		self.assertNotIn("Storage charges", text)

	def test_delivery_note_names_the_transporter(self):
		job = make()
		text = _text(frappe.get_print("Operations", job.name, "Job Delivery Note"))
		self.assertIn("Truck No: ____", text)

		supplier = frappe.get_all("Supplier", pluck="name", limit=1)[0]
		make_transportation(job, transporter=supplier)
		text = _text(frappe.get_print("Operations", job.name, "Job Delivery Note"))
		name = frappe.db.get_value("Supplier", supplier, "supplier_name")
		self.assertIn(f"Transporter: {name}", text)


class TestServiceTypeFilter(P1TestCase):
	# C26 -----------------------------------------------------------------------

	def test_activity_code_filtered_by_mode(self):
		df = frappe.get_meta("Operations").get_field("activity_code")
		filters = json.loads(df.link_filters)
		self.assertEqual(filters[0][:3], ["Freight Activity Code", "mode", "="])
		self.assertIn("doc.mode_of_shipment", filters[0][3])

		sea = frappe.get_all("Freight Activity Code", filters={"mode": "Sea"}, pluck="name")
		self.assertTrue(sea)
		self.assertNotIn("Air Foreign Freight", sea)


class TestPorts(P1TestCase):
	# C27 -----------------------------------------------------------------------

	def test_same_origin_and_destination_refused(self):
		port = _port("ZZP1A", "P1 Test Port")
		with self.assertRaises(frappe.ValidationError):
			make(mode_of_shipment="Sea", svc_freight_forwarding=1, port_of_loading=port, port_of_destination=port)

	def test_existing_job_with_same_ports_must_be_fixed_to_save(self):
		port = _port("ZZP1A", "P1 Test Port")
		other = _port("ZZP1B", "P1 Other Port")
		job = make(mode_of_shipment="Sea", svc_freight_forwarding=1, port_of_loading=port, port_of_destination=other)
		frappe.db.set_value("Operations", job.name, "port_of_destination", port)
		job.reload()
		self.assertRaises(frappe.ValidationError, job.save)  # a legacy job is blocked too
		job.reload()
		job.port_of_destination = other
		job.save()  # and saves once corrected


class TestWizardCargo(P1TestCase):
	# C28 -----------------------------------------------------------------------

	CARGO = ["packages", "net_weight", "gross_weight", "weight_uom", "cbm", "cargo_description"]

	def test_defaults_carry_the_cargo_fields(self):
		cargo = next(s for s in ui_config.default_wizard("New Job")["steps"] if s["key"] == "cargo")
		names = [f["fieldname"] for f in cargo["fields"]]
		for fieldname in self.CARGO:
			self.assertIn(fieldname, names)

	def test_patch_appends_only_the_missing_fields(self):
		if not frappe.db.exists(ui_config.WIZARD_LAYOUT, {"wizard": "New Job"}):
			self.skipTest("No New Job wizard layout on this site")
		layout = frappe.get_doc(ui_config.WIZARD_LAYOUT, {"wizard": "New Job"})
		kept = [r for r in layout.fields if r.fieldname not in self.CARGO[1:]]
		for row in kept:
			if row.fieldname == "packages":
				row.hidden = 1  # an admin's choice
		layout.set("fields", kept)
		layout.save(ignore_permissions=True)

		add_wizard_cargo_fields.execute()
		add_wizard_cargo_fields.execute()  # idempotent

		layout.reload()
		cargo = [r for r in layout.fields if r.section == "cargo"]
		names = [r.fieldname for r in cargo]
		for fieldname in self.CARGO:
			self.assertEqual(names.count(fieldname), 1, fieldname)
		packages = next(r for r in cargo if r.fieldname == "packages")
		self.assertEqual(packages.hidden, 1)


class TestDuplicateQuote(P1TestCase):
	# C29 — an expired quote is reused by duplicating it --------------------------

	def test_expired_quote_is_copied_with_a_fresh_window(self):
		from forwarding.quote_to_job import duplicate_quote

		customer = frappe.get_all("Customer", pluck="name", limit=1)[0]
		old = frappe.get_doc(
			{
				"doctype": "Quote",
				"consignee": customer,
				"mode": "SEA",
				"date": add_days(nowdate(), -40),
				"validity": add_days(nowdate(), -26),
				"items": [{"description": "Ocean Freight", "rate": 100, "units": 1, "amount": 100}],
			}
		).insert(ignore_permissions=True)

		name = duplicate_quote(old.name)
		copy = frappe.get_doc("Quote", name)
		self.assertNotEqual(name, old.name)
		self.assertEqual(getdate(copy.date), getdate(nowdate()))
		self.assertEqual(getdate(copy.validity), getdate(add_days(nowdate(), 14)))
		self.assertEqual((copy.consignee, len(copy.items)), (customer, 1))
		self.assertEqual(getdate(frappe.db.get_value("Quote", old.name, "validity")), getdate(add_days(nowdate(), -26)))
