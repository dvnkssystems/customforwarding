# Copyright (c) 2026, DVNKS Systems and contributors
"""Data for the "Proof of Delivery" print format on a job (Operations).

The print format only lays things out. Here: the company header, the job's
BL/AWB, consignee and delivery details, what is being delivered (containers,
else packages, else the job's own piece count), and who delivers it (the
job's latest Transportation that is not cancelled).

`?containers=<row name>,<row name>` in the print URL limits the POD to those
containers. It replaced the Job Delivery Note (ONE Freight, 2 Nov): the job's
"Proof of Delivery" print button asks which containers when there are several.

Delivery time, driver and truck come from the Transportation, and when the
job itself lists no containers its Transportation's containers are the goods.
"""

import frappe
from frappe.utils import cint, flt, format_time, formatdate

from forwarding.invoice_print import address_lines, company_header


def _place(value):
	"""A location as people write it: a leading "-" from the Port master dropped."""
	return (value or "").lstrip("- ").strip()


_KIND = {"sea": "Port", "air": "Airport"}


def port_label(value):
	"""A Port as the prints show it: "Ad Dammam Port (SADMM)", not its record
	name "SADMM-Ad Dammam" (ONE Freight, 3 Nov). Sea ports get "Port", airports
	"Airport", unless the name already says so; anything that is not a Port
	record prints as typed."""
	if not value:
		return ""
	port = frappe.db.get_value("Port", value, ["port_name", "port_code", "mode_of_shipment"], as_dict=True)
	if not port or not (port.port_name or "").strip():
		return _place(value)
	name = port.port_name.strip()
	kind = _KIND.get((port.mode_of_shipment or "").lower())
	if kind and kind.lower() not in name.lower():
		name = f"{name} {kind}"
	code = (port.port_code or "").strip(" -")
	return f"{name} ({code})" if code and code.lower() != port.port_name.strip().lower() else name


def _join(*parts, sep=" / "):
	return sep.join(str(p) for p in parts if p)


def _weight(value):
	return f"{flt(value, 3):,g}" if flt(value) else ""


def _containers(doc, rows=None):
	picked = [c for c in (frappe.form_dict.get("containers") or "").split(",") if c]
	if rows is None:
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
		fields=["name", "transporter", "driver", "vehicle", "delivery_date", "delivery_time", "destination_location_address"],
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
		delivery_time=t.delivery_time,
		address=t.destination_location_address or "",
		containers=frappe.get_all(
			"Container Details",
			filters={"parenttype": "Transportation", "parent": t.name},
			fields=["*"],
			order_by="idx",
		),
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
	if not lines and transport.get("containers"):
		lines = _containers(doc, transport.containers)
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
		consignee=doc.get("consignee") or customer_name,
		shipper=doc.get("shipper") or "",
		carrier_label=carrier_label,
		carrier_label_ar=carrier_label_ar,
		carrier=carrier,
		port=port_label(doc.get("port_of_destination")),
		delivery_address=", ".join(
			address_lines(transport.get("address") or doc.get("delivery_address") or doc.get("place_of_delivery"))
		),
		delivery_date=formatdate(delivery_date) if delivery_date else "",
		delivery_time=format_time(transport.delivery_time, "HH:mm") if transport.get("delivery_time") else "",
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
