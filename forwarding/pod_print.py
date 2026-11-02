# Copyright (c) 2026, DVNKS Systems and contributors
"""Data for the "Proof of Delivery" print format on a job (Operations).

The print format only lays things out. Here: the company header, the job's
BL/AWB, consignee and delivery details, what is being delivered (containers,
else packages, else the job's own piece count), and who delivers it (the
job's latest Transportation that is not cancelled).

`?containers=<row name>,<row name>` in the print URL limits the POD to those
containers, as the Job Delivery Note does.
"""

import frappe
from frappe.utils import cint, flt, formatdate

from forwarding.invoice_print import company_header


def _place(value):
	"""A location as people write it: a leading "-" from the Port master dropped."""
	return (value or "").lstrip("- ").strip()


def _join(*parts, sep=" / "):
	return sep.join(str(p) for p in parts if p)


def _weight(value):
	return f"{flt(value, 3):,g}" if flt(value) else ""


def _containers(doc):
	picked = [c for c in (frappe.form_dict.get("containers") or "").split(",") if c]
	rows = doc.get("container_details") or []
	if picked:
		rows = [r for r in rows if r.name in picked]
	lines = []
	for i, row in enumerate(rows, 1):
		size = f"{row.size}'" if row.get("size") else ""
		lines.append(
			frappe._dict(
				idx=i,
				ref=row.get("container_no") or "",
				kind=_join(size, row.get("container_type"), sep=" "),
				seal=row.get("seal_no") or "",
				packages=cint(row.get("packages")) or "",
				weight=_weight(row.get("weight")),
				description=row.get("cargo_description") or doc.get("cargo_description") or "",
			)
		)
	return lines


def _packages(doc):
	lines = []
	for i, row in enumerate(doc.get("package_details") or [], 1):
		dims = "x".join(str(cint(v)) for v in (row.get("length"), row.get("width"), row.get("height")) if cint(v))
		lines.append(
			frappe._dict(
				idx=i,
				ref=row.get("package_type") or "",
				kind=f"{dims} cm" if dims else "",
				seal="",
				packages="%g" % flt(row.get("quantity")) if flt(row.get("quantity")) else "",
				weight=_weight(row.get("total_weight") or row.get("weight")),
				description=row.get("remarks") or doc.get("cargo_description") or "",
			)
		)
	return lines


def _transport(doc):
	"""Transporter, driver, truck and delivery date of the latest Transportation."""
	if not frappe.db.exists("DocType", "Transportation"):
		return frappe._dict()
	rows = frappe.get_all(
		"Transportation",
		filters={"operations": doc.name, "docstatus": ["<", 2]},
		fields=["transporter", "driver", "vehicle", "delivery_date", "destination_location_address"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return frappe._dict()
	t = rows[0]
	return frappe._dict(
		transporter=(frappe.db.get_value("Supplier", t.transporter, "supplier_name") or t.transporter)
		if t.transporter
		else "",
		driver=(frappe.db.get_value("Driver", t.driver, "full_name") or t.driver) if t.driver else "",
		vehicle=t.vehicle or "",
		delivery_date=t.delivery_date,
		address=t.destination_location_address or "",
	)


def get_pod_context(doc):
	"""Everything the Proof of Delivery print format shows."""
	company = doc.get("company") or frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	transport = _transport(doc) if doc.get("name") else frappe._dict()

	mode = (doc.get("mode_of_shipment") or "").lower()
	if mode == "air":
		carrier_label, carrier_label_ar = "Airline / Flight", "شركة الطيران / الرحلة"
		carrier = _join(doc.get("air_line"), doc.get("flight_number"))
	else:
		carrier_label, carrier_label_ar = "Vessel / Voyage", "السفينة / الرحلة"
		carrier = _join(doc.get("vessel_name"), doc.get("voyage_number"))

	lines = _containers(doc)
	unit = "containers"
	if not lines:
		lines = _packages(doc)
		unit = "packages"

	customer_name = (
		frappe.db.get_value("Customer", doc.customer, "customer_name") if doc.get("customer") else ""
	) or doc.get("customer") or ""
	delivery_date = doc.get("delivery_date") or transport.get("delivery_date")

	return frappe._dict(
		company=company_header(company),
		job_no=doc.get("name") or "",
		bl_awb=doc.get("awb_number") or doc.get("mbl_number") or "",
		hbl=doc.get("house_number") or "",
		customer=customer_name,
		consignee=doc.get("consignee") or "",
		shipper=doc.get("shipper") or "",
		carrier_label=carrier_label,
		carrier_label_ar=carrier_label_ar,
		carrier=carrier,
		port=_place(doc.get("port_of_destination")),
		delivery_address=doc.get("delivery_address") or transport.get("address") or doc.get("place_of_delivery") or "",
		delivery_date=formatdate(delivery_date) if delivery_date else "",
		lines=lines,
		unit=unit,
		total_packages=doc.get("no_of_pieces") or doc.get("packages") or "",
		total_weight=_weight(doc.get("gross_weight")),
		weight_uom=doc.get("weight_uom") or "Kg",
		cargo=doc.get("cargo_description") or "",
		transporter=transport.get("transporter") or "",
		driver=transport.get("driver") or "",
		vehicle=transport.get("vehicle") or "",
		printed_on=formatdate(frappe.utils.nowdate()),
	)
