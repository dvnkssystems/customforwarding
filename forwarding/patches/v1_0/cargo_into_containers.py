# Copyright (c) 2026, DVNKS Systems and contributors
"""Older jobs' cargo figures move onto their container rows.

Cargo Details (packages, net and gross weight, CBM) is now the total of the
job's container rows. A job saved before had the figures on the job and none
on its rows:

- one container row: the figures go on it;
- several rows: they go on the first row, so the totals stay the same, and
  the job is listed below to be split by container by hand;
- no container row, on a job that takes containers (not Air, cargo layout
  Containers or unset): one row is added holding the figures.

Jobs with package rows keep them as the source, and the job's own fields are
not touched. Rows that already carry figures are left alone, so running it
again changes nothing.
"""

import frappe
from frappe.utils import cstr, flt

from forwarding.forwarding.doctype.operations.operations import seed_container_cargo


def execute():
	frappe.reload_doc("forwarding", "doctype", "container_details")

	with_packages = set(
		frappe.get_all("Package", filters={"parenttype": "Operations"}, pluck="parent", distinct=True)
	)
	jobs = frappe.get_all(
		"Operations",
		filters={"docstatus": ["<", 2]},
		fields=["name", "mode_of_shipment", "cargo_layout", "packages", "net_weight", "gross_weight", "cbm", "volume"],
	)
	rows_by_job = {}
	for row in frappe.get_all(
		"Container Details",
		filters={"parenttype": "Operations", "parentfield": "container_details"},
		fields=["name", "parent", "idx", "packages", "net_weight", "weight", "volume"],
		order_by="parent, idx",
	):
		rows_by_job.setdefault(row.parent, []).append(row)

	split_by_hand = []
	for job in jobs:
		if job.name in with_packages:
			continue
		rows = rows_by_job.get(job.name, [])
		if rows:
			first = seed_container_cargo(frappe._dict(job, container_details=rows))
			if first:
				frappe.db.set_value(
					"Container Details",
					first.name,
					{f: first[f] for f in ("packages", "net_weight", "weight", "volume")},
					update_modified=False,
				)
				if len(rows) > 1:
					split_by_hand.append(job.name)
		elif job.mode_of_shipment != "Air" and cstr(job.cargo_layout) in ("", "Containers"):
			row = frappe._dict(name=None)
			if seed_container_cargo(frappe._dict(job, container_details=[row])) is None:
				continue
			frappe.get_doc(
				{
					"doctype": "Container Details",
					"parent": job.name,
					"parenttype": "Operations",
					"parentfield": "container_details",
					"idx": 1,
					"qty": 1,
					"packages": row.packages,
					"net_weight": flt(row.net_weight),
					"weight": flt(row.weight),
					"volume": flt(row.volume),
				}
			).db_insert()

	if split_by_hand:
		print(f"Cargo put on the first of several containers ({len(split_by_hand)} jobs):")
		print(", ".join(split_by_hand))
