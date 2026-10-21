# Copyright (c) 2026, DVNKS Systems and contributors
"""Let the job form follow the Operations DocType's own field order (D6).

Sites carry a `field_order` Property Setter on Operations left behind by an
old Customize Form save. Frappe sorts the form by it ahead of the DocType
JSON, so a field the JSON moves (ATD / ATA into Departure & Arrival) stays
where the stale list put it. Removing it hands the order back to the JSON;
Custom Fields keep their own insert_after.

Also drops the Property Setter that hid ATA Delay Reason, which now sits
beside ATA as ATD Delay Reason does beside ATD.
"""

import frappe

STALE = (
	{"doc_type": "Operations", "property": "field_order"},
	{"doc_type": "Operations", "field_name": "ata_delay_reason", "property": "hidden"},
)


def execute():
	removed = 0
	for filters in STALE:
		for name in frappe.get_all("Property Setter", filters=filters, pluck="name"):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
			removed += 1
	if removed:
		frappe.clear_cache(doctype="Operations")
