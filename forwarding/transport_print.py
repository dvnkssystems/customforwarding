# Copyright (c) 2026, DVNKS Systems and contributors
"""Data for the "Transport Order" print format on a Transportation.

A one-page order for the driver (ONE Freight, 2 Nov, item 17): the job and
its BL/AWB, the route with addresses and dates, the truck and driver, and the
containers. No costs, accounts or amounts: the default layout printed the
cost table and ran off the page.

Containers are the Transportation's own, else the job's.
"""

import frappe
from frappe.utils import format_time, formatdate

from forwarding.invoice_print import address_lines, company_header
from forwarding.pod_print import _containers, _join, _weight, port_label


def _name(doctype, name, field):
	if not name:
		return ""
	return frappe.db.get_value(doctype, name, field) or name


def get_transport_order_context(doc):
	"""Everything the Transport Order print format shows."""
	job = frappe.get_doc("Operations", doc.operations) if doc.get("operations") else frappe._dict()
	company = job.get("company") or frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)

	lines = _containers(job, doc.get("container_details") or [])
	if not lines and job:
		lines = _containers(job)

	driver = frappe._dict()
	if doc.get("driver"):
		driver = frappe.db.get_value("Driver", doc.driver, ["full_name", "cell_number"], as_dict=True) or frappe._dict()

	mode = (job.get("mode_of_shipment") or "").lower()
	carrier = (
		_join(job.get("air_line"), job.get("flight_number"))
		if mode == "air"
		else _join(job.get("vessel_name"), job.get("voyage_number"))
	)
	customer = doc.get("customer") or job.get("customer")

	return frappe._dict(
		company=company_header(company),
		order_no=doc.name,
		status=doc.get("transport_status") or "Planned",
		job_no=job.get("name") or "",
		bl_awb=job.get("awb_number") or job.get("mbl_number") or "",
		carrier=carrier,
		port=port_label(job.get("port_of_destination")),
		customer=_name("Customer", customer, "customer_name"),
		consignee=job.get("consignee") or _name("Customer", customer, "customer_name"),
		cargo=job.get("cargo_description") or "",
		gross_weight=_weight(job.get("gross_weight")),
		weight_uom=job.get("weight_uom") or "Kg",
		transporter=_name("Supplier", doc.get("transporter"), "supplier_name") or doc.get("transportation_by") or "",
		vehicle=doc.get("vehicle") or "",
		driver=driver.get("full_name") or doc.get("driver") or "",
		driver_mobile=driver.get("cell_number") or "",
		from_place=doc.get("departure_location") or "",
		from_address=address_lines(doc.get("departure_location_address")),
		to_place=doc.get("destination_location") or "",
		to_address=address_lines(doc.get("destination_location_address")),
		pickup_date=formatdate(doc.pickup_date) if doc.get("pickup_date") else "",
		delivery_date=formatdate(doc.delivery_date) if doc.get("delivery_date") else "",
		delivery_time=format_time(doc.delivery_time, "HH:mm") if doc.get("delivery_time") else "",
		lines=lines,
		printed_on=formatdate(frappe.utils.nowdate()),
	)
