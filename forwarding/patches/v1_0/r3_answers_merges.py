# Copyright (c) 2026, DVNKS Systems and contributors
"""Merges agreed with Simran on 27 Oct.

- Shipment Type TRUCK into FTL, so a Land job is FTL or LTL (its 4 jobs move).
- Ports NS-NHAVASHEVA and JNPT-NHAVA SHEVA into INNSA-Nhava Sheva.

A merge repoints every link to the record merged away, then removes it. Each
is skipped when either side is missing, so the patch runs on any site.
"""

import frappe
from frappe.model.rename_doc import rename_doc

MERGES = [
	("Shipment Type", "TRUCK", "FTL"),
	("Port", "NS-NHAVASHEVA", "INNSA-Nhava Sheva"),
	("Port", "JNPT-NHAVA SHEVA", "INNSA-Nhava Sheva"),
]


def execute():
	for doctype, old, new in MERGES:
		if frappe.db.exists(doctype, old) and frappe.db.exists(doctype, new):
			rename_doc(doctype, old, new, merge=True, force=True, show_alert=False)
