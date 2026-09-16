# Copyright (c) 2026, DVNKS Systems and contributors
"""Backfill the cargo layout and free time on existing records.

* Shipment Type gets a cargo layout: FCL uses container rows, LCL loose cargo,
  and every other type tied to a mode weight only.
* Each job copies its shipment type's layout, which the form's section rules
  read. Jobs without a shipment type keep a blank layout and show every section.
* Free time moves from the old free-text field to a number of days, where the
  old value was a plain number, and its expiry is worked out from ETA.

Only blank values are filled, so anything already set by hand stays.
"""

import frappe

LAYOUTS = {"FCL": "Containers", "LCL": "Loose Cargo"}


def execute():
	for shipment_type in frappe.get_all("Shipment Type", fields=["name", "mode_of_shipment", "cargo_layout"]):
		if shipment_type.cargo_layout:
			continue
		layout = LAYOUTS.get(shipment_type.name) or ("Weight Only" if shipment_type.mode_of_shipment else None)
		if layout:
			frappe.db.set_value("Shipment Type", shipment_type.name, "cargo_layout", layout, update_modified=False)

	frappe.db.sql(
		"""
		update `tabOperations` job
		join `tabShipment Type` shipment_type on shipment_type.name = job.shipment_type
		set job.cargo_layout = shipment_type.cargo_layout
		where ifnull(job.cargo_layout, '') = ''
		"""
	)

	frappe.db.sql(
		"""
		update `tabOperations`
		set free_time_days = cast(trim(free_time) as unsigned)
		where ifnull(free_time_days, 0) = 0
			and trim(ifnull(free_time, '')) regexp '^[0-9]+$'
		"""
	)

	frappe.db.sql(
		"""
		update `tabOperations`
		set free_time_expiry = date_add(eta_date, interval free_time_days day)
		where free_time_days > 0 and eta_date is not null and free_time_expiry is null
		"""
	)
