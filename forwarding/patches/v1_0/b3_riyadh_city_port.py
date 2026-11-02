# Copyright (c) 2026, DVNKS Systems and contributors
"""The "port_code-RIYADH CITY" port (B3-20).

A 2024 import named ports `{port_code}-{port_name}` with the code missing, so
the record reads "port_code-RIYADH CITY" in every job's POL / POD. It is the
Land port for Riyadh city, used by about 90 of the client's jobs, and no other
Riyadh record is a Land port (the rest are the airport, the dry port and stray
copies), so there is nothing to merge it into. It gets Riyadh's UN/LOCODE,
SARUH, and is renamed to match (SARUH-RIYADH CITY); the rename repoints every
job and quote that uses it.

Skipped when the record is missing; when the new name already exists the old
record is merged into it. Running it again changes nothing.
"""

import frappe
from frappe.model.rename_doc import rename_doc

OLD = "port_code-RIYADH CITY"
CODE = "SARUH"
NEW = f"{CODE}-RIYADH CITY"


def execute():
	if not frappe.db.exists("Port", OLD):
		return
	merge = bool(frappe.db.exists("Port", NEW))
	if not merge:
		frappe.db.set_value("Port", OLD, "port_code", CODE, update_modified=False)
	rename_doc("Port", OLD, NEW, merge=merge, force=True, show_alert=False)
