# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""One document list per job (R3-36): a Custom Clearance's Documents table is
the job's Document Table rows with Stage = Customs Clearance, kept in step
both ways.

Both records keep real rows (so frappe.client.get, prints and reports read
them as before); each save mirrors its rows onto the other record with direct
row writes, so neither record is saved again and nothing loops.

Rows are paired by Document and, for a document listed twice, by its order
among the rows of that document ("the second Commercial Invoice").

Clearance saved (Custom Clearance.on_update -> `sync_to_job`)
	Every clearance row is a customs row (its Stage is set on validate).
	Paired job rows take the clearance row's values; a clearance row with no
	partner is added to the job; a job row whose partner the clearance had
	before this save and no longer has is deleted from the job (removed
	here, removed there). A customs row on the job the clearance never had
	(added on the job since) is added to the clearance.

Job saved (Operations on_update -> `sync_from_job`)
	The job is the reference: each clearance of the job (not cancelled) ends
	up with exactly the job's customs rows, updated, added or deleted.

The other record's `modified` moves on when its rows change, so a form open
on stale rows is refused on save ("has been modified") instead of writing
the old list back over the new one.
"""

import frappe
from frappe.utils import cstr, now

CUSTOMS = "Customs Clearance"
TABLE = "Document Table"
FIELD = "document_table"
# What a row carries across; stage is always Customs Clearance on both sides.
SYNC_FIELDS = (
	"document",
	"received",
	"date",
	"attach",
	"remark",
	"uploaded_on",
	"uploaded_by",
	"ocr_status",
	"extracted_data",
)


def is_customs(row):
	return cstr(row.get("stage")).strip() == CUSTOMS


def _keyed(rows):
	"""{(document, nth): row} in idx order."""
	seen, keyed = {}, {}
	for row in sorted(rows, key=lambda r: r.get("idx") or 0):
		doc = cstr(row.get("document")).strip()
		seen[doc] = seen.get(doc, 0) + 1
		keyed[(doc, seen[doc])] = row
	return keyed


def _db_rows(parenttype, parent):
	return frappe.get_all(
		TABLE,
		filters={"parenttype": parenttype, "parent": parent, "parentfield": FIELD},
		fields=["name", "idx", "stage", *SYNC_FIELDS],
		order_by="idx",
	)


def _values(row):
	return {f: row.get(f) for f in SYNC_FIELDS}


def _differs(a, b):
	return any(cstr(a.get(f)) != cstr(b.get(f)) for f in SYNC_FIELDS)


def _insert(parenttype, parent, row, idx):
	child = frappe.get_doc(
		{
			"doctype": TABLE,
			"parenttype": parenttype,
			"parent": parent,
			"parentfield": FIELD,
			"idx": idx,
			"stage": CUSTOMS,
			**_values(row),
		}
	)
	child.db_insert()
	return child


def _touch(doctype, name):
	frappe.db.set_value(doctype, name, "modified", now(), update_modified=False)


def mark_customs_rows(clearance):
	"""Custom Clearance validate: every row of its Documents table is a
	customs row, whatever stage it was added with."""
	for row in clearance.get(FIELD) or []:
		row.stage = CUSTOMS


def sync_to_job(clearance):
	"""Mirror a saved clearance's rows onto its job (see module docstring)."""
	if not clearance.get("operations") or clearance.docstatus == 2:
		return
	job = clearance.operations
	before = clearance.get_doc_before_save()
	had = set(_keyed(before.get(FIELD) or [])) if before else set()

	all_job_rows = _db_rows("Operations", job)
	job_rows = _keyed([r for r in all_job_rows if is_customs(r)])
	mine = _keyed(clearance.get(FIELD) or [])
	next_idx = max((r.idx for r in all_job_rows), default=0) + 1
	changed = False

	for key, row in mine.items():
		partner = job_rows.get(key)
		if partner is None:
			_insert("Operations", job, row, next_idx)
			next_idx += 1
			changed = True
		elif _differs(row, partner):
			frappe.db.set_value(TABLE, partner.name, _values(row), update_modified=False)
			changed = True

	pulled = False
	next_own = max((r.idx for r in clearance.get(FIELD) or []), default=0) + 1
	for key, partner in job_rows.items():
		if key in mine:
			continue
		if key in had:
			frappe.db.delete(TABLE, {"name": partner.name})
			changed = True
		else:
			row = clearance.append(FIELD, {**_values(partner), "stage": CUSTOMS, "idx": next_own})
			row.db_insert()
			next_own += 1
			pulled = True

	if changed:
		_touch("Operations", job)
	if pulled:
		_touch(clearance.doctype, clearance.name)


def sync_from_job(job, method=None):
	"""Operations on_update: give each of the job's clearances exactly the
	job's customs rows."""
	if job.docstatus == 2:
		return
	clearances = frappe.get_all("Custom Clearance", filters={"operations": job.name, "docstatus": ["<", 2]}, pluck="name")
	if not clearances:
		return
	job_rows = _keyed([r for r in job.get(FIELD) or [] if is_customs(r)])
	for name in clearances:
		theirs = _keyed(_db_rows("Custom Clearance", name))
		next_idx = max((r.idx for r in theirs.values()), default=0) + 1
		changed = False
		for key, row in job_rows.items():
			partner = theirs.get(key)
			if partner is None:
				_insert("Custom Clearance", name, row, next_idx)
				next_idx += 1
				changed = True
			elif _differs(row, partner) or not is_customs(partner):
				frappe.db.set_value(TABLE, partner.name, {**_values(row), "stage": CUSTOMS}, update_modified=False)
				changed = True
		for key, partner in theirs.items():
			if key not in job_rows:
				frappe.db.delete(TABLE, {"name": partner.name})
				changed = True
		if changed:
			_touch("Custom Clearance", name)
