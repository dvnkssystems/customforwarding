# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 2 §7.2: several services per job, decided by its Scope of Work
(M-05, M-06, M-21) and its mode and job type (R2-23)."""

import frappe
from frappe.tests import IntegrationTestCase

from forwarding import services
from forwarding.api import job_360
from forwarding.patches.v1_0 import r2_scope_multi
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


def scope_rows(*names):
	return [{"scope_of_work": scope(n)} for n in names]


def sea_import(scope_name, *codes, **values):
	"""A Sea Import job; scope_name is one scope or a tuple of several."""
	names = scope_name if isinstance(scope_name, tuple) else (scope_name,)
	return make(
		mode_of_shipment="Sea",
		job_type=values.pop("job_type", "Import"),
		scope_of_work=scope(names[0]),
		scopes_of_work=scope_rows(*names),
		services=rows(*codes),
		**values,
	)


def drop_scopes(job):
	"""Make the job one saved before it had a Scope of Work."""
	frappe.db.delete("Job Scope Of Work", {"parent": job.name, "parenttype": "Operations"})
	job.db_set("scope_of_work", None)
	job.reload()


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

	def test_client_scope_list_seeded(self):
		ff, cc, tr = "Freight Forwarding", "Customs Clearance", "Transportation"
		docs = "Documentation & Certification"
		for name, types in (
			("Port to Port", {ff}),
			("Port to Door", {ff, cc, tr}),
			("Door to Port", {ff, cc, tr}),
			("Door to Door", {ff, cc, tr}),
			("Custom Clearance", {cc}),
			("Destination Clearance", {cc}),
			("Customs Clearance + Transportation", {cc, tr}),
			("Transportation", {tr}),
			("SABER Services", {docs}),
			("Product Test Report", {docs}),
			(
				"Other Services",
				{"Warehousing", "Packing & Relocation", "Value Added Services", "Cargo Insurance", "Trading"},
			),
		):
			# The exact name, and exactly its types: nothing is allowed with every scope.
			self.assertTrue(frappe.db.get_value("Scope Of Work", {"name": name}, "name") == name, name)
			self.assertEqual(services.allowed_service_types(name), types, name)
		for old in ("Customs Clearance only", "Transportation only"):
			self.assertFalse(frappe.db.exists("Scope Of Work", old), old)

	def test_seed_is_idempotent(self):
		before = frappe.db.count("Scope Of Work")
		r2_scope_multi.seed_scopes()
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
		# No longer allowed with every scope.
		self.assertNotIn("Warehousing", found)

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
		new.scopes_of_work = []
		with self.assertRaises(frappe.ValidationError) as caught:
			new.insert(ignore_permissions=True)
		self.assertIn("Scope of Work", str(caught.exception))

	def test_old_job_without_scope_still_saves(self):
		job = make(mode_of_shipment="Sea", services=rows(FREEHAND))
		drop_scopes(job)
		job.po_no = "PO-R2-SERVICES"
		job.save(ignore_permissions=True)
		self.assertEqual(job.svc_freight_forwarding, 1)

	def test_scope_can_be_set_on_an_old_job(self):
		job = make(mode_of_shipment="Sea", services=rows(FREEHAND))
		drop_scopes(job)
		# An older client sets the one field; it becomes the table's first row.
		job.scope_of_work = scope("Port to Port")
		job.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Operations", job.name, "scope_of_work"), scope("Port to Port"))
		self.assertEqual(services.job_scopes(job), [scope("Port to Port")])
		self.assertEqual(len(job.scopes_of_work), 1)


class TestNewServiceTypes(IntegrationTestCase):
	# M-21 ----------------------------------------------------------------------

	def test_each_new_type_has_a_code(self):
		for service_type in ("Warehousing", "Packing & Relocation", "Cargo Insurance", "Documentation & Certification"):
			self.assertTrue(
				frappe.db.exists("Freight Activity Code", {"service_type": service_type}), service_type
			)

	def test_new_types_tick_their_boxes(self):
		job = sea_import(
			("Port to Port", "Other Services"), FREEHAND, "Warehousing", "Packing & Relocation", "Cargo Insurance"
		)
		self.assertEqual((job.svc_warehousing, job.svc_packing_relocation), (1, 1))
		self.assertIn("Cargo Insurance", services.job_service_types(job))


class TestSeveralScopes(IntegrationTestCase):
	# Simran, 24 Oct: a job holds several Scopes of Work ------------------------

	def test_services_of_any_chosen_scope(self):
		job = sea_import(("Port to Port", "Custom Clearance"), FREEHAND, SEA_IMPORT_CLEARANCE)
		self.assertEqual(services.job_scopes(job), [scope("Port to Port"), scope("Custom Clearance")])
		self.assertEqual(services.job_service_types(job), ["Freight Forwarding", "Customs Clearance"])
		# The first scope is the job's scope_of_work, for prints and reports.
		abbreviation = frappe.db.get_value("Scope Of Work", scope("Port to Port"), "abbreviation")
		self.assertEqual(job.scope_of_work, scope("Port to Port"))
		self.assertEqual(job.sow_abb, abbreviation)
		self.assertEqual((job.freight_forwarding, job.custom_clearance, job.transport), ("1", "1", "0"))

	def test_no_type_is_allowed_with_every_scope(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			sea_import("Port to Port", FREEHAND, "Warehousing")
		self.assertIn("Warehousing", str(caught.exception))

	def test_payload_and_method_agree(self):
		job = sea_import(("Port to Port", "Custom Clearance"), FREEHAND)
		payload = job_360.build(job.name)["job"]
		self.assertEqual(payload["scopes_of_work"], [scope("Port to Port"), scope("Custom Clearance")])
		self.assertEqual(payload["allowed_service_types"], ["Freight Forwarding", "Customs Clearance"])
		self.assertEqual(
			services.scope_service_types(frappe.as_json(payload["scopes_of_work"])),
			payload["allowed_service_types"],
		)
		self.assertIsNone(services.scope_service_types("[]"))

	def test_picker_follows_every_scope(self):
		def found(scopes):
			return {
				r[1]
				for r in services.activity_code_query(
					"Freight Activity Code",
					"",
					"name",
					0,
					200,
					{"mode_of_shipment": "Sea", "job_type": "Import", "scopes_of_work": frappe.as_json(scopes)},
				)
			}

		port = found([scope("Port to Port")])
		both = found([scope("Port to Port"), scope("Transportation")])
		self.assertNotIn("Transportation", port)
		self.assertIn("Transportation", both)
		self.assertNotIn("Customs Clearance", both)

	def test_one_row_per_scope(self):
		job = sea_import(("Port to Port", "Port to Port", "Custom Clearance"), FREEHAND)
		self.assertEqual([r.scope_of_work for r in job.scopes_of_work], [scope("Port to Port"), scope("Custom Clearance")])

	def test_removing_every_scope_from_a_saved_job(self):
		job = sea_import("Port to Port", FREEHAND)
		job.scopes_of_work = []
		job.save(ignore_permissions=True)
		# Not put back from scope_of_work: the job no longer restricts.
		self.assertIsNone(job.scope_of_work)
		self.assertEqual(services.job_scopes(job), [])

	def test_removing_a_scope_a_clearance_needs(self):
		job = sea_import(("Port to Port", "Custom Clearance"), FREEHAND)
		clearance = frappe.get_doc(
			{"doctype": "Custom Clearance", "operations": job.name, "clearance_status": "Draft"}
		)
		clearance.flags.ignore_mandatory = True
		clearance.insert(ignore_permissions=True)

		job.reload()
		job.scopes_of_work = [r for r in job.scopes_of_work if r.scope_of_work == scope("Port to Port")]
		with self.assertRaises(frappe.ValidationError) as caught:
			job.save(ignore_permissions=True)
		self.assertIn(clearance.name, str(caught.exception))

		# Once the clearance is gone, the scope can go.
		frappe.delete_doc("Custom Clearance", clearance.name, ignore_permissions=True, force=True)
		job.reload()
		job.scopes_of_work = [r for r in job.scopes_of_work if r.scope_of_work == scope("Port to Port")]
		job.save(ignore_permissions=True)
		self.assertEqual(services.job_scopes(job), [scope("Port to Port")])

	def test_removing_the_last_scope_a_clearance_needs(self):
		# A-01: no scope left is not "unrestricted" for a job that had one.
		job = sea_import("Customs Clearance + Transportation", SEA_IMPORT_CLEARANCE)
		clearance = frappe.get_doc(
			{"doctype": "Custom Clearance", "operations": job.name, "clearance_status": "Draft"}
		)
		clearance.flags.ignore_mandatory = True
		clearance.insert(ignore_permissions=True)

		job.reload()
		job.scopes_of_work = []
		with self.assertRaises(frappe.ValidationError) as caught:
			job.save(ignore_permissions=True)
		self.assertIn(clearance.name, str(caught.exception))

	def test_removing_a_scope_a_service_needs(self):
		job = sea_import(("Port to Port", "Custom Clearance"), FREEHAND, SEA_IMPORT_CLEARANCE)
		job.scopes_of_work = [r for r in job.scopes_of_work if r.scope_of_work == scope("Port to Port")]
		with self.assertRaises(frappe.ValidationError) as caught:
			job.save(ignore_permissions=True)
		self.assertIn(SEA_IMPORT_CLEARANCE, str(caught.exception))

	def test_out_of_scope_box_raises_no_alert(self):
		# Port to Port with a clearance box ticked by hand: no B7, no clearance service.
		job = sea_import(("Port to Port", "Transportation"), FREEHAND, LOCAL_FREIGHT)
		job.db_set("svc_customs_clearance", 1)
		job.reload()
		self.assertNotIn("Customs Clearance", services.job_service_types(job))
		self.assertNotIn("B7", banner_codes(job))

	def test_backfill_moves_the_one_scope_into_the_table(self):
		job = sea_import("Port to Port", FREEHAND)
		frappe.db.delete("Job Scope Of Work", {"parent": job.name, "parenttype": "Operations"})
		r2_scope_multi.backfill_job_scopes()
		r2_scope_multi.backfill_job_scopes()  # idempotent
		job.reload()
		self.assertEqual([r.scope_of_work for r in job.scopes_of_work], [scope("Port to Port")])
