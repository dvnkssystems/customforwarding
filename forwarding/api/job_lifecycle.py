# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Cancel, delete and amend a job (Round 2: R2-09, R2-11, R2-34).

The job page's More menu calls these instead of frappe.client.cancel /
delete_doc, so the rules about what is linked to the job live in one place:

cancel_job   A submitted job is cancelled only when nothing submitted hangs
             off it: no submitted Sales or Purchase Invoice, no submitted
             payment against them, no Transportation or Custom Clearance
             (those are never submitted, so any that is not deleted counts).
             Draft invoices and payments linked to the job are deleted with
             the cancel, once the caller confirms it (`delete_drafts`).
delete_job   A draft or cancelled job is deleted only when no invoice,
             payment, Transportation or Custom Clearance (draft or submitted)
             still points at it.
amend_job    A cancelled job, not amended yet, as a new unsaved draft linked
             through amended_from: Frappe's own amend, done on the server so
             the page opens the copy in the job form.

linked_records() is what all three read; the page asks it first so it can
name the records in its confirmation before anything is changed.
"""

import frappe
from frappe import _
from frappe.utils import cint

JOB = "Operations"
INVOICES = ("Sales Invoice", "Purchase Invoice")
# Linked by `operations`, and not submittable: one that exists is a live record.
SERVICES = ("Transportation", "Custom Clearance")


def linked_records(job):
	"""Every record linked to the job that is not cancelled, in the order a
	user would deal with them (payments, invoices, services):

	[{"doctype", "name", "docstatus"}]"""
	invoices = {
		dt: frappe.get_all(
			dt,
			filters={"operations": job, "docstatus": ["<", 2]},
			fields=["name", "docstatus"],
			order_by="creation asc",
		)
		for dt in INVOICES
	}
	out = [dict(r, doctype="Payment Entry") for r in _payments(job, invoices)]
	for dt in INVOICES:
		out.extend(dict(r, doctype=dt) for r in invoices[dt])
	for dt in SERVICES:
		out.extend(
			dict(r, doctype=dt, docstatus=0)
			for r in frappe.get_all(
				dt, filters={"operations": job, "docstatus": ["<", 2]}, fields=["name"], order_by="creation asc"
			)
		)
	return [{"doctype": r["doctype"], "name": r["name"], "docstatus": cint(r["docstatus"])} for r in out]


def _payments(job, invoices):
	"""Payment Entries (not cancelled) settling the job's invoices, or booked
	against its Project, which is named after the job."""
	pe = frappe.qb.DocType("Payment Entry")
	ref = frappe.qb.DocType("Payment Entry Reference")
	found = {}
	for dt in INVOICES:
		names = [r.name for r in invoices[dt]]
		if not names:
			continue
		rows = (
			frappe.qb.from_(pe)
			.join(ref)
			.on(ref.parent == pe.name)
			.select(pe.name, pe.docstatus, pe.creation)
			.where((ref.reference_doctype == dt) & ref.reference_name.isin(names) & (pe.docstatus < 2))
			.run(as_dict=True)
		)
		for r in rows:
			found[r.name] = r
	for r in frappe.get_all(
		"Payment Entry",
		filters={"project": job, "docstatus": ["<", 2]},
		fields=["name", "docstatus", "creation"],
	):
		found[r.name] = r
	return sorted(found.values(), key=lambda r: (r.creation, r.name))


def cancel_blockers(links):
	"""What has to be cancelled (or deleted) before the job can be: submitted
	invoices and payments, and any Transportation or Custom Clearance."""
	return [r for r in links if r["docstatus"] == 1 or r["doctype"] in SERVICES]


def cancel_drafts(links):
	"""Draft invoices and payments, deleted together with the job's cancel."""
	return [r for r in links if r["docstatus"] == 0 and r["doctype"] not in SERVICES]


def _list(rows):
	"""Payment Entry PE-0001, Sales Invoice JSI-26-0003"""
	return ", ".join(f"{_(r['doctype'])} {frappe.bold(r['name'])}" for r in rows)


@frappe.whitelist(methods=["GET"])
def check(job):
	"""What cancelling or deleting the job would run into, for the page's
	confirmation: {docstatus, links, cancel: {blockers, drafts},
	delete: {blockers}, amended_to}."""
	doc = frappe.get_doc(JOB, job)
	doc.check_permission("read")
	links = linked_records(job)
	return {
		"docstatus": doc.docstatus,
		"links": links,
		"cancel": {"blockers": cancel_blockers(links), "drafts": cancel_drafts(links)},
		"delete": {"blockers": links},
		"amended_to": _amended_to(job),
	}


@frappe.whitelist(methods=["POST"])
def cancel_job(job, delete_drafts=0):
	"""Cancel a submitted job. Refused while anything submitted is linked;
	draft invoices / payments linked to it are deleted first, but only with
	delete_drafts set (the user confirmed the list)."""
	doc = frappe.get_doc(JOB, job)
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted job can be cancelled."), title=_("Cannot cancel"))

	links = linked_records(job)
	blockers = cancel_blockers(links)
	if blockers:
		frappe.throw(
			_("Cancel {0} first. They are linked to job {1}.").format(_list(blockers), frappe.bold(job)),
			title=_("Linked records"),
		)

	drafts = cancel_drafts(links)
	if drafts and not cint(delete_drafts):
		frappe.throw(
			_("Draft {0} linked to job {1}. Confirm to delete them and cancel the job.").format(
				_list(drafts), frappe.bold(job)
			),
			title=_("Draft records linked"),
		)

	for r in drafts:
		frappe.delete_doc(r["doctype"], r["name"])
	doc.reload()
	doc.cancel()
	return {"name": job, "docstatus": doc.docstatus, "deleted": drafts}


@frappe.whitelist(methods=["POST"])
def delete_job(job):
	"""Delete a draft or cancelled job, once nothing live points at it."""
	doc = frappe.get_doc(JOB, job)
	if doc.docstatus == 1:
		frappe.throw(_("A submitted job cannot be deleted. Cancel it first."), title=_("Cannot delete"))
	if not frappe.has_permission(JOB, "delete", doc):
		frappe.throw(_("You are not allowed to delete job {0}.").format(frappe.bold(job)), frappe.PermissionError)

	links = linked_records(job)
	if links:
		frappe.throw(
			_("Job {0} cannot be deleted while these are linked to it: {1}. Delete or cancel them first.").format(
				frappe.bold(job), _list(links)
			),
			title=_("Linked records"),
		)
	amended = _amended_to(job)
	if amended:
		frappe.throw(
			_("Job {0} was amended as {1}. Delete {1} first.").format(frappe.bold(job), frappe.bold(amended)),
			title=_("Linked records"),
		)

	frappe.delete_doc(JOB, job)
	return {"name": job, "deleted": True}


@frappe.whitelist(methods=["POST"])
def amend_job(job):
	"""The cancelled job as a new unsaved draft, amended_from set; the page
	opens it in the job form, where saving gives it the next amended name
	(R-IM-S-26-07024-1)."""
	doc = frappe.get_doc(JOB, job)
	doc.check_permission("read")
	if not frappe.has_permission(JOB, "create") or not frappe.has_permission(JOB, "amend", doc):
		frappe.throw(_("You are not allowed to amend job {0}.").format(frappe.bold(job)), frappe.PermissionError)
	if doc.docstatus != 2:
		frappe.throw(_("Only a cancelled job can be amended."), title=_("Cannot amend"))
	amended = _amended_to(job)
	if amended:
		frappe.throw(
			_("Job {0} has already been amended as {1}.").format(frappe.bold(job), frappe.bold(amended)),
			title=_("Cannot amend"),
		)

	# As the desk's Amend does: no_copy fields left out, the rest kept.
	copy = frappe.copy_doc(doc, ignore_no_copy=False)
	copy.amended_from = job
	copy.docstatus = 0
	for row in copy.get_all_children():
		row.docstatus = 0
		row.parent = None
	return copy.as_dict(convert_dates_to_str=True)


def _amended_to(job):
	"""The job's live amendment (draft or submitted), if any."""
	return frappe.db.get_value(JOB, {"amended_from": job, "docstatus": ["<", 2]}, "name")
