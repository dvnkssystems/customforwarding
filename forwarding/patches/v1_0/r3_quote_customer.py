# Copyright (c) 2026, DVNKS Systems and contributors
"""Quote gets a required Customer (R3-43).

Quote is a custom DocType carried by fixtures/doctype.json, and migrate syncs
fixtures only after the patches, so the fixture is imported first.

Old quotes kept the payer in Consignee (a Customer link) and Create Job made
it the job's customer, so a quote with a Consignee and no Customer takes it as
its Customer: same payer as before. Consignee is left as it is. Direct
updates; the quotes are not saved.
"""

import frappe


def sync_quote_fixture():
	"""Import the Quote / Quote Item DocTypes from the fixture (idempotent)."""
	from frappe.core.doctype.data_import.data_import import import_doc

	import_doc(frappe.get_app_path("forwarding", "fixtures", "doctype.json"))
	frappe.clear_cache(doctype="Quote")


def execute():
	sync_quote_fixture()
	for row in frappe.get_all(
		"Quote",
		filters={"customer": ["is", "not set"], "consignee": ["is", "set"]},
		fields=["name", "consignee"],
	):
		name = frappe.db.get_value("Customer", row.consignee, "customer_name")
		if name is None:
			continue
		frappe.db.set_value(
			"Quote",
			row.name,
			{"quote_to": "Customer", "customer": row.consignee, "party_name": name},
			update_modified=False,
		)
	q = frappe.qb.DocType("Quote")
	frappe.qb.update(q).set(q.quote_to, "Customer").where(q.quote_to.isnull() | (q.quote_to == "")).run()
