# Copyright (c) 2026, DVNKS Systems and contributors
"""One document list per job (R3-36): bring each Custom Clearance's
Documents table in line with its job's Customs Clearance rows.

For every clearance not cancelled:

1. Rows of its hidden "Clearance Documents" table (Operations Clearance
   Document) whose Type names a Document List record move into Documents
   (document, date, file, number and expiry in the remark). Rows whose Type
   names no document stay where they were and are counted in the log.
2. A Documents row with another stage is a copy of a job row when the job
   lists the same document; it is dropped. Otherwise it becomes a customs row.
3. The two lists are merged (forwarding.clearance_documents.sync_to_job with
   nothing removed): rows only on the clearance go to the job, customs rows
   only on the job come to the clearance.

Direct row writes; the records are not saved.
"""

import frappe
from frappe.utils import cstr

from forwarding.clearance_documents import CUSTOMS, FIELD, TABLE, is_customs, sync_to_job


def execute():
	frappe.reload_doc("forwarding", "doctype", "custom_clearance")
	documents = {name.lower(): name for name in frappe.get_all("Document List", pluck="name")}
	unmatched = 0
	for name in frappe.get_all("Custom Clearance", filters={"docstatus": ["<", 2], "operations": ["is", "set"]}, pluck="name"):
		clearance = frappe.get_doc("Custom Clearance", name)
		unmatched += move_legacy_rows(clearance, documents)
		job_documents = {
			cstr(d).strip()
			for d in frappe.get_all(
				TABLE, filters={"parenttype": "Operations", "parent": clearance.operations, "parentfield": FIELD}, pluck="document"
			)
		}
		for row in list(clearance.get(FIELD) or []):
			if is_customs(row):
				continue
			if cstr(row.document).strip() in job_documents:
				frappe.db.delete(TABLE, {"name": row.name})
				clearance.remove(row)
			else:
				row.stage = CUSTOMS
				row.db_update()
		sync_to_job(clearance)
	if unmatched:
		print(f"r3_clearance_documents_shared: {unmatched} Clearance Documents rows name no Document List record; left in place")


def move_legacy_rows(clearance, documents):
	unmatched = 0
	for old in list(clearance.get("clearance_documents") or []):
		document = documents.get(cstr(old.document_type).strip().lower())
		if not document:
			unmatched += 1
			continue
		remark = " · ".join(
			part
			for part in (
				cstr(old.document_number).strip(),
				f"Expires {old.expiry_date}" if old.expiry_date else "",
			)
			if part
		)
		row = clearance.append(
			FIELD,
			{
				"document": document,
				"stage": CUSTOMS,
				"date": old.document_date,
				"attach": old.attachment,
				"received": "Yes" if old.attachment else None,
				"remark": remark or None,
			},
		)
		row.db_insert()
		frappe.db.delete("Operations Clearance Document", {"name": old.name})
		clearance.remove(old)
	return unmatched
