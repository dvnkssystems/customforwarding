# Copyright (c) 2026, DVNKS Systems and contributors
"""Fill the empty Departure / Destination of existing Transportation records
from their job (R3-42). Only empty fields; nothing typed is overwritten.
Direct updates, so the records are not saved."""

import frappe


def execute():
	from forwarding.forwarding.doctype.transportation.transportation import ROUTE_FIELDS, route_values

	for row in frappe.get_all("Transportation", filters={"operations": ["is", "set"]}, fields=["name", "operations", *ROUTE_FIELDS]):
		values = {k: v for k, v in route_values(row.operations).items() if not row.get(k)}
		if values:
			frappe.db.set_value("Transportation", row.name, values, update_modified=False)
