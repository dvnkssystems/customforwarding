# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-06): drop document rows that name no document.

"+ Add document" saved rows with nothing chosen (QA: J-IM-A-26-07049,
"Document 1 - Awaiting" and two "Document required"). Saving now refuses
them (forwarding.child_tables.validate_document_rows); this removes the
ones already stored, on every parent, so those records save again.

* Document Table: a row with no Document and no file is dropped, whatever
  else it says (a remark or "received" on a row that names nothing has
  nothing to be about). A row with a file but no Document is kept, so no
  attachment is lost, and is listed in the patch log for someone to name.
* Operations Clearance Document: a row with no Document Type, number or
  attachment is dropped.

The remaining rows of each parent touched are renumbered 1..n. Running it
again changes nothing.
"""

import frappe

BLANK = ("", None)


def _blank(value):
	return value in BLANK or not str(value).strip()


def execute():
	touched = set()
	dropped = 0

	for row in frappe.get_all(
		"Document Table",
		filters=[["document", "is", "not set"]],
		fields=["name", "parent", "parenttype", "parentfield", "attach"],
	):
		if not _blank(row.attach):
			print(f"R3-06: kept {row.parenttype} {row.parent} document row {row.name}: it has a file but no Document")
			continue
		frappe.db.delete("Document Table", {"name": row.name})
		touched.add(("Document Table", row.parenttype, row.parent, row.parentfield))
		dropped += 1

	if frappe.db.table_exists("Operations Clearance Document"):
		for row in frappe.get_all(
			"Operations Clearance Document",
			fields=["name", "parent", "parenttype", "parentfield", "document_type", "document_number", "attachment"],
		):
			if all(_blank(row.get(f)) for f in ("document_type", "document_number", "attachment")):
				frappe.db.delete("Operations Clearance Document", {"name": row.name})
				touched.add(("Operations Clearance Document", row.parenttype, row.parent, row.parentfield))
				dropped += 1

	for doctype, parenttype, parent, parentfield in touched:
		names = frappe.get_all(
			doctype,
			filters={"parenttype": parenttype, "parent": parent, "parentfield": parentfield},
			order_by="idx asc",
			pluck="name",
		)
		for idx, name in enumerate(names, start=1):
			frappe.db.set_value(doctype, name, "idx", idx, update_modified=False)

	print(f"R3-06: dropped {dropped} blank document rows on {len({(p, n) for _d, p, n, _f in touched})} records")
