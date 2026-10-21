# Copyright (c) 2026, DVNKS Systems and contributors
"""Work out the package rows' chargeable weight and the header cargo totals
of every job that has package rows (C5, C6), so existing jobs show them
without being saved again. Jobs without package rows are not touched."""

import frappe

HEADER = (
	"total_package_qty",
	"total_package_volume",
	"total_package_weight",
	"total_chargeable_weight",
	"packages",
	"no_of_pieces",
	"gross_weight",
	"cbm",
	"volume",
	"chargable_weight",
)


def execute():
	jobs = frappe.get_all(
		"Package",
		filters={"parenttype": "Operations", "parentfield": "package_details"},
		pluck="parent",
		distinct=True,
	)
	for name in jobs:
		doc = frappe.get_doc("Operations", name)
		if doc.docstatus == 2:
			continue
		doc.calculate_package_totals()
		for row in doc.package_details:
			row.db_set(
				{"volume": row.volume, "total_weight": row.total_weight, "chargeable_weight": row.chargeable_weight},
				update_modified=False,
			)
		doc.db_set({f: doc.get(f) for f in HEADER}, update_modified=False)
	frappe.cache.delete_keys("job_360")
