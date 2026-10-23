# Copyright (c) 2026, DVNKS Systems and contributors
"""Quote becomes submittable (M-08), with Status, Shipper and Salesman.

Quote is a custom DocType carried by fixtures/doctype.json, and migrate syncs
fixtures only after the patches, so the fixture is imported here first: that
adds is_submittable and the status / amended_from / shipper / salesman columns.

Existing quotes:

* A quote some job was already made from (Operations.from_quotation, job not
  cancelled) counts as submitted. Its prices are what that job was priced on;
  leaving it a draft would let them change under the job, and Create Job is
  only offered on a submitted quote anyway.
* Every other quote stays a draft (status Draft), to be submitted when it is
  approved. An expired draft is not submitted; it can be duplicated or have
  its validity extended first.

Submitting is a direct docstatus update on the quote and its child rows: the
quotes are not saved, so nothing else runs and validity is not re-checked.
"""

import frappe
from frappe.core.doctype.data_import.data_import import import_doc

CHILD_TABLES = ("Quote Item", "Shipment Parcel", "Container Details")


def execute():
	import_doc(frappe.get_app_path("forwarding", "fixtures", "doctype.json"))
	frappe.clear_cache(doctype="Quote")
	set_quote_states()


def set_quote_states():
	"""Submit the draft quotes jobs were made from; give the rest a status."""
	used = set(
		frappe.get_all(
			"Operations",
			filters={"from_quotation": ["is", "set"], "docstatus": ["<", 2]},
			pluck="from_quotation",
		)
	)
	for row in frappe.get_all("Quote", fields=["name", "docstatus", "status"]):
		if row.docstatus == 0 and row.name in used:
			frappe.db.set_value("Quote", row.name, {"docstatus": 1, "status": "Submitted"}, update_modified=False)
			for child in CHILD_TABLES:
				frappe.db.set_value(
					child,
					{"parent": row.name, "parenttype": "Quote"},
					"docstatus",
					1,
					update_modified=False,
				)
		elif not row.status:
			status = {0: "Draft", 1: "Submitted", 2: "Cancelled"}[row.docstatus]
			frappe.db.set_value("Quote", row.name, "status", status, update_modified=False)
