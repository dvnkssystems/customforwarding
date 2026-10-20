# Copyright (c) 2026, DVNKS Systems and contributors
"""Bring existing jobs up to the Job 360 fields.

* ATA is shown on the form again: a site Property Setter had hidden it.
* Billing status moves to No Invoice / Invoiced / Partly Paid / Paid,
  worked out from each job's submitted Sales Invoices.
* Free time now runs from the ATA when there is one, else the ETA.
* Air jobs get chargeable weight = max(gross weight, CBM x 167).

Values are written straight to the table so submitted jobs are covered and
modified dates are left alone.
"""

import frappe
from frappe.utils import add_days, cint, flt

from forwarding.forwarding.doctype.operations.operations import AIR_VOLUMETRIC_FACTOR
from forwarding.job_events import get_billing_status


def execute():
	frappe.db.delete(
		"Property Setter", {"doc_type": "Operations", "field_name": "ata_date", "property": "hidden"}
	)
	frappe.clear_cache(doctype="Operations")

	jobs = frappe.get_all(
		"Operations",
		fields=[
			"name",
			"billing_status",
			"mode_of_shipment",
			"gross_weight",
			"cbm",
			"chargable_weight",
			"ata_date",
			"eta_date",
			"free_time_days",
			"free_time_expiry",
		],
	)
	for job in jobs:
		values = {"billing_status": get_billing_status(job.name)}

		days = cint(job.free_time_days)
		start = job.ata_date or job.eta_date
		values["free_time_expiry"] = add_days(start, days) if start and days > 0 else None

		if job.mode_of_shipment == "Air" and (flt(job.gross_weight) or flt(job.cbm)):
			values["chargable_weight"] = max(flt(job.gross_weight), flt(job.cbm) * AIR_VOLUMETRIC_FACTOR)

		changed = {k: v for k, v in values.items() if str(job.get(k) or "") != str(v or "")}
		if changed:
			frappe.db.set_value("Operations", job.name, changed, update_modified=False)
