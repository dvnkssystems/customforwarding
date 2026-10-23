# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 2 §7.2: several services per job, decided by its Scope of Work
(M-05, M-06, M-21) and its mode and job type (R2-23)."""

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import services
from forwarding.api import job_360
from forwarding.patches.v1_0 import r2_services_and_scopes
from forwarding.tests.test_job_360 import make

FREEHAND = "Sea Import Freehand"
SEA_IMPORT_CLEARANCE = "Sea Import Clearance"
SEA_EXPORT_CLEARANCE = "Sea Export Clearance"
LOCAL_FREIGHT = "Land Local Freight"


def scope(name):
	"""A seeded scope, by the client's name, whatever its case on this site."""
	found = next((n for n in frappe.get_all("Scope Of Work", pluck="name") if n.lower() == name.lower()), None)
	if not found:
		raise frappe.DoesNotExistError(f"Scope {name} not seeded")
	return found


def rows(*codes):
	return [{"activity_code": c} for c in codes]


def sea_import(scope_name, *codes, **values):
	return make(
		mode_of_shipment="Sea",
		job_type=values.pop("job_type", "Import"),
		scope_of_work=scope(scope_name),
		services=rows(*codes),
		**values,
	)


def banner_codes(job):
	return {b["rule_code"] for b in job_360.build(job.name)["banners"]}


class TestServices(IntegrationTestCase):
	def test_door_to_door_holds_three_services(self):
		job = sea_import("Door to Door", FREEHAND, SEA_IMPORT_CLEARANCE, LOCAL_FREIGHT)
		self.assertEqual(job.activity_code, FREEHAND)
		self.assertEqual(job.service_list, f"{FREEHAND}, {SEA_IMPORT_CLEARANCE}, {LOCAL_FREIGHT}")
		self.assertEqual(
			(job.svc_freight_forwarding, job.svc_customs_clearance, job.svc_transportation), (1, 1, 1)
		)
		self.assertEqual(
			services.job_service_types(job), ["Freight Forwarding", "Customs Clearance", "Transportation"]
		)

	def test_removing_a_service_unticks_its_box(self):
		job = sea_import("Door to Door", FREEHAND, SEA_IMPORT_CLEARANCE)
		job.services = [r for r in job.services if r.activity_code == FREEHAND]
		job.save(ignore_permissions=True)
		self.assertEqual((job.svc_freight_forwarding, job.svc_customs_clearance), (1, 0))

	def test_activity_code_alone_becomes_the_first_service(self):
		job = make(mode_of_shipment="Sea", activity_code=FREEHAND)
		self.assertEqual([r.activity_code for r in job.services], [FREEHAND])
		self.assertEqual(job.svc_freight_forwarding, 1)

	def test_payload_lists_every_service(self):
		job = sea_import("Door to Door", FREEHAND, SEA_IMPORT_CLEARANCE)
		payload = job_360.build(job.name)["job"]
		self.assertEqual([s["activity_code"] for s in payload["services"]], [FREEHAND, SEA_IMPORT_CLEARANCE])
		self.assertEqual(payload["service_types"], ["Freight Forwarding", "Customs Clearance"])
		self.assertEqual(payload["scope_of_work"], scope("Door to Door"))


class TestModeAndJobType(IntegrationTestCase):
	# R2-23 ---------------------------------------------------------------------

	def test_import_job_refuses_export_code(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			sea_import("Door to Door", FREEHAND, SEA_EXPORT_CLEARANCE)
		self.assertIn("Export", str(caught.exception))

	def test_changing_job_type_rechecks_the_codes(self):
		job = sea_import("Door to Door", FREEHAND)
		job.job_type = "Export"
		self.assertRaises(frappe.ValidationError, job.save, ignore_permissions=True)

	def test_air_job_refuses_sea_code(self):
		with self.assertRaises(frappe.ValidationError):
			make(mode_of_shipment="Air", scope_of_work=scope("Door to Door"), services=rows(SEA_IMPORT_CLEARANCE))

	def test_trucking_suits_any_mode(self):
		job = sea_import("Door to Door", LOCAL_FREIGHT)
		self.assertEqual(job.svc_transportation, 1)

	def test_picker_offers_only_matching_codes(self):
		found = {
			r[0]
			for r in services.activity_code_query(
				"Freight Activity Code", "", "name", 0, 100, {"mode_of_shipment": "Sea", "job_type": "Import"}
			)
		}
		self.assertIn(FREEHAND, found)
		self.assertIn(LOCAL_FREIGHT, found)
		self.assertNotIn(SEA_EXPORT_CLEARANCE, found)
		self.assertNotIn("Air Freight Import", found)


class TestScopeOfWork(IntegrationTestCase):
	# M-06 ----------------------------------------------------------------------

	def test_seven_scopes_seeded(self):
		ff, cc, tr = "Freight Forwarding", "Customs Clearance", "Transportation"
		for name, types in (
			("Port to Port", {ff}),
			("Port to Door", {ff, cc, tr}),
			("Door to Port", {ff, cc, tr}),
			("Door to Door", {ff, cc, tr}),
			("Customs Clearance only", {cc}),
			("Customs Clearance + Transportation", {cc, tr}),
			("Transportation only", {tr}),
		):
			allowed = services.allowed_service_types(scope(name))
			self.assertEqual(allowed - set(services.ALWAYS_ALLOWED), types, name)

	def test_seed_is_idempotent(self):
		before = frappe.db.count("Scope Of Work")
		r2_services_and_scopes.seed_scopes()
		self.assertEqual(frappe.db.count("Scope Of Work"), before)

	def test_port_to_port_offers_only_freight(self):
		found = {
			r[1]
			for r in services.activity_code_query(
				"Freight Activity Code",
				"",
				"name",
				0,
				100,
				{"mode_of_shipment": "Sea", "job_type": "Import", "scope_of_work": scope("Port to Port")},
			)
		}
		self.assertIn("Freight Forwarding", found)
		self.assertNotIn("Customs Clearance", found)
		self.assertNotIn("Transportation", found)
		# Allowed with every scope.
		self.assertIn("Warehousing", found)

	def test_port_to_port_refuses_clearance(self):
		with self.assertRaises(frappe.ValidationError):
			sea_import("Port to Port", FREEHAND, SEA_IMPORT_CLEARANCE)

	def test_port_to_port_has_no_clearance_alert(self):
		job = sea_import("Port to Port", FREEHAND)
		# A box ticked by hand outside the scope raises nothing either.
		job.db_set("svc_customs_clearance", 1)
		job.reload()
		self.assertEqual(services.job_service_types(job), ["Freight Forwarding"])
		self.assertNotIn("B7", banner_codes(job))

	def test_door_to_door_with_only_clearance(self):
		job = sea_import("Door to Door", SEA_IMPORT_CLEARANCE)
		self.assertEqual(services.job_service_types(job), ["Customs Clearance"])
		self.assertEqual(job.svc_transportation, 0)
		self.assertIn("B7", banner_codes(job))

	def test_clearance_and_transport_scope(self):
		job = sea_import("Customs Clearance + Transportation", SEA_IMPORT_CLEARANCE, LOCAL_FREIGHT)
		self.assertEqual(services.job_service_types(job), ["Customs Clearance", "Transportation"])
		with self.assertRaises(frappe.ValidationError):
			job.append("services", {"activity_code": FREEHAND})
			job.save(ignore_permissions=True)

	def test_new_job_needs_a_scope(self):
		job = make(mode_of_shipment="Sea")
		new = frappe.copy_doc(job)
		new.scope_of_work = None
		with self.assertRaises(frappe.ValidationError) as caught:
			new.insert(ignore_permissions=True)
		self.assertIn("Scope of Work", str(caught.exception))

	def test_old_job_without_scope_still_saves(self):
		job = make(mode_of_shipment="Sea", services=rows(FREEHAND))
		job.db_set("scope_of_work", None)
		job.reload()
		job.po_no = "PO-R2-SERVICES"
		job.save(ignore_permissions=True)
		self.assertEqual(job.svc_freight_forwarding, 1)

	def test_scope_can_be_set_on_an_old_job(self):
		job = make(mode_of_shipment="Sea", services=rows(FREEHAND))
		job.db_set("scope_of_work", None)
		job.reload()
		job.scope_of_work = scope("Port to Port")
		job.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Operations", job.name, "scope_of_work"), scope("Port to Port"))


class TestNewServiceTypes(IntegrationTestCase):
	# M-21 ----------------------------------------------------------------------

	def test_each_new_type_has_a_code(self):
		for service_type in ("Warehousing", "Packing & Relocation", "Cargo Insurance", "Documentation & Certification"):
			self.assertTrue(
				frappe.db.exists("Freight Activity Code", {"service_type": service_type}), service_type
			)

	def test_new_types_tick_their_boxes(self):
		job = sea_import("Port to Port", FREEHAND, "Warehousing", "Packing & Relocation", "Cargo Insurance")
		self.assertEqual((job.svc_warehousing, job.svc_packing_relocation), (1, 1))
		self.assertIn("Cargo Insurance", services.job_service_types(job))
