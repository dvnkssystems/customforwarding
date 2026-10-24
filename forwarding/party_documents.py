# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Party Documents: the CR, VAT certificate, licences, insurance and contracts
kept on a Customer or Supplier (Phase 2 spec §5.3, CU3, SU9).

A row's expiry status is about today, so it is never trusted from storage:
validate() sets it when the party is saved, for the desk form, and rows()
works it out again every time the 360 payload is built.

	Expired		expiry_date before today
	Expiring	expiry_date from today up to Party Alert Settings'
			Document Expiry Warning (Days) ahead, both ends included
	Valid		expiry_date later than that
	No expiry	no expiry_date
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, getdate, nowdate

FIELD = "party_documents"

VALID = "Valid"
EXPIRING = "Expiring"
EXPIRED = "Expired"
NO_EXPIRY = "No expiry"

# Order of the payload list: the rows needing attention first.
STATUS_ORDER = {EXPIRED: 0, EXPIRING: 1, VALID: 2, NO_EXPIRY: 3}


def expiry_days():
	from forwarding.forwarding.doctype.party_alert_settings.party_alert_settings import get_settings

	return get_settings().document_expiry_days


def expiry_status(expiry_date, today=None, days=None):
	if not expiry_date:
		return NO_EXPIRY
	today = getdate(today or nowdate())
	left = date_diff(getdate(expiry_date), today)
	if left < 0:
		return EXPIRED
	if left <= cint(expiry_days() if days is None else days):
		return EXPIRING
	return VALID


def validate(doc, method=None):
	"""Customer / Supplier validate: an expiry date is not before the issue
	date, and each row's expiry status is set for today."""
	rows = doc.get(FIELD) or []
	if not rows:
		return
	today, days = getdate(nowdate()), expiry_days()
	for row in rows:
		if row.issue_date and row.expiry_date and getdate(row.expiry_date) < getdate(row.issue_date):
			frappe.throw(
				_("Row {0}: {1} expiry date cannot be before its issue date").format(
					row.idx, _(row.document_type or "Document")
				),
				title=_("Invalid Expiry Date"),
			)
		row.expiry_status = expiry_status(row.expiry_date, today, days)


def rows(doc, today=None, days=None):
	"""The party's document rows for the 360 payload, expired first, then
	expiring, valid and no expiry; within each, soonest expiry first.

	[{name, document_type, document_no, issue_date, expiry_date, attach,
	expiry_status, days_left}], days_left being expiry_date - today in days
	(None without an expiry date)."""
	today = getdate(today or nowdate())
	days = expiry_days() if days is None else days
	out = []
	for row in doc.get(FIELD) or []:
		expiry = getdate(row.expiry_date) if row.expiry_date else None
		out.append(
			{
				"name": row.name,
				"document_type": row.document_type,
				"document_no": row.document_no or None,
				"issue_date": getdate(row.issue_date) if row.issue_date else None,
				"expiry_date": expiry,
				"attach": row.attach or None,
				"expiry_status": expiry_status(expiry, today, days),
				"days_left": date_diff(expiry, today) if expiry else None,
				"_idx": row.idx,
			}
		)
	out.sort(key=lambda r: (STATUS_ORDER[r["expiry_status"]], r["expiry_date"] or today, r["_idx"]))
	for r in out:
		del r["_idx"]
	return out


def attached_urls(parenttype, parent):
	"""File URLs on the party's Party Document rows."""
	return frappe.get_all(
		"Party Document",
		filters={"parenttype": parenttype, "parent": parent, "parentfield": FIELD, "attach": ["is", "set"]},
		pluck="attach",
	)


def on_file(row):
	"""A row counts towards Documents on file when it has a file or a number."""
	return bool(row.get("attach") or row.get("document_no"))


def summary(documents):
	"""(kpis, expiring rows, expired rows) for the payload and the banners."""
	expiring = [r for r in documents if r["expiry_status"] == EXPIRING]
	expired = [r for r in documents if r["expiry_status"] == EXPIRED]
	kpis = {
		"party_documents_count": len(documents),
		"party_documents_expiring": len(expiring),
		"party_documents_expired": len(expired),
	}
	return kpis, expiring, expired
