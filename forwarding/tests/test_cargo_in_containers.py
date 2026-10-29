# Copyright (c) 2026, DVNKS Systems and contributors
"""Cargo Details is the total of the job's container rows."""

import frappe
from frappe.tests import IntegrationTestCase

from forwarding.api import job_360
from forwarding.forwarding.doctype.operations.operations import seed_container_cargo, set_cargo_totals
from forwarding.tests.test_job_360 import CUSTOMER, make as make_job


def make(**values):
	# Any customer when the demo one is missing (a site with client data).
	if not frappe.db.exists("Customer", CUSTOMER):
		values["customer"] = frappe.db.get_value("Customer", {"disabled": 0}, "name")
	return make_job(**values)


def save(job):
	job.flags.ignore_mandatory = True
	job.save(ignore_permissions=True)
	job.reload()
	return job


class TestCargoInContainers(IntegrationTestCase):
	def test_job_cargo_is_the_rows_total(self):
		job = make(mode_of_shipment="Sea")
		job.append("container_details", {"container_no": "MSCU1000001", "packages": 10, "net_weight": 900, "weight": 1000, "volume": 12.5})
		job.append("container_details", {"container_no": "MSCU1000002", "packages": 5, "net_weight": 400, "weight": 450, "volume": 7.25})
		save(job)
		self.assertEqual(job.packages, "15")
		self.assertEqual(job.no_of_pieces, 15)
		self.assertEqual(job.net_weight, 1300)
		self.assertEqual(job.gross_weight, 1450)
		self.assertEqual(job.cbm, 19.75)

		(unit,) = [u for u in job_360.build(job.name)["units"] if u["label"] == "MSCU1000002"]
		self.assertEqual(unit["cargo"]["gross_weight"], 450)
		self.assertEqual(unit["cargo"]["packages"], 5)

	def test_figures_without_rows_stay_typed(self):
		job = make(mode_of_shipment="Sea")
		job.packages, job.gross_weight = "8 pcs", 300
		save(job)
		self.assertEqual(job.packages, "8 pcs")
		self.assertEqual(job.gross_weight, 300)

	def test_wording_kept_when_the_count_matches(self):
		job = frappe._dict(packages="17 PALLETS", container_details=[frappe._dict(packages=17)])
		set_cargo_totals(job)
		self.assertEqual(job.packages, "17 PALLETS")
		job.container_details[0].packages = 20
		set_cargo_totals(job)
		self.assertEqual(job.packages, "20")

	def test_old_job_figures_go_on_the_first_row(self):
		first, second = frappe._dict(), frappe._dict()
		job = frappe._dict(packages="764", net_weight=10112.7, gross_weight=10112.7, cbm=0, container_details=[first, second])
		self.assertIs(seed_container_cargo(job), first)
		self.assertEqual((first.packages, first.weight), (764, 10112.7))
		set_cargo_totals(job)
		self.assertEqual((job.packages, job.gross_weight), ("764", 10112.7))
		# Rows that carry figures are the source; nothing is copied again.
		self.assertIsNone(seed_container_cargo(job))
