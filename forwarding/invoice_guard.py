# Copyright (c) 2026, DVNKS Systems and contributors
"""A job is invoiced only once it is submitted (R3-03).

Sales and Purchase Invoices reach a job through their `operations` field.
Raising one against a draft job billed work nobody had confirmed yet (QA:
JSI-26-0003 on the draft R-IM-A-26-07014), and against a cancelled job it
bills a job that no longer stands. Wired up as a validate doc_event on both
invoice DocTypes, so it holds for every path that saves one -- the desk, the
Vue app, frappe.client and the make_* mappers -- and on submit too, since
submit runs validate.
"""

import frappe
from frappe import _
from frappe.utils import cint

INVOICE_DOCTYPES = ("Sales Invoice", "Purchase Invoice")


def _skip():
	return frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch


def job_not_submitted_message(job, doctype, docstatus):
	if cint(docstatus) == 2:
		return _("Job {0} is cancelled. A {1} can only be raised against a submitted job.").format(
			frappe.bold(job), _(doctype)
		)
	return _("Job {0} is still a draft. Submit the job before raising a {1} against it.").format(
		frappe.bold(job), _(doctype)
	)


def assert_job_submitted(job, doctype):
	"""Throw unless `job` is a submitted Operations job."""
	if not job:
		return
	docstatus = frappe.db.get_value("Operations", job, "docstatus")
	if docstatus is None or cint(docstatus) == 1:
		# A job that does not exist is the Link validation's to report.
		return
	frappe.throw(job_not_submitted_message(job, doctype, docstatus), title=_("Job not submitted"))


def validate(doc, method=None):
	"""validate on Sales Invoice / Purchase Invoice."""
	if _skip() or doc.doctype not in INVOICE_DOCTYPES:
		return
	assert_job_submitted(doc.get("operations"), doc.doctype)
