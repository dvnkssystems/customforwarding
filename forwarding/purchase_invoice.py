# Copyright (c) 2026, DVNKS Systems and contributors
"""Purchase Invoice rules for freight costs (Phase 2 spec §5.6).

A bill counts towards a job (the job's costs, the supplier's Cost variance)
through Purchase Invoice.operations. A bill with no job is allowed but warned
about, and a bill with a job takes the job's Project, Branch and Cost Center,
so its GL entries land on the job and its branch; Sales Invoices do the same.
"""

import frappe
from frappe import _

def _skip():
	return frappe.flags.in_import or frappe.flags.in_migrate or frappe.flags.in_patch or frappe.flags.in_install


def fill_from_job(doc, method=None):
	"""before_validate: the bill's Project, Branch and Cost Center are its
	job's, on the bill and on every item (A-02); the form shows them read-only.

	A bill with no job carries no job's Project (A-03): one left over from an
	earlier pick, or a remembered default, is cleared. Another Project — not a
	job's — is the user's and is kept. Used for Sales Invoices too."""
	rows = [doc, *(doc.get("items") or [])]
	# A row sent with a default's literal text (":Company", A-05) takes the
	# bill's cost center, else the company's.
	fallback_cc = doc.get("cost_center") or (
		frappe.get_cached_value("Company", doc.company, "cost_center") if doc.get("company") else None
	)
	for row in rows[1:]:
		if str(row.get("cost_center") or "").startswith(":"):
			row.cost_center = fallback_cc
	if not doc.get("operations"):
		for row in rows:
			if row.get("project") and frappe.db.exists("Operations", row.project):
				row.project = None
		return
	dimensions = job_dimensions(doc.operations, doc.company)
	for row in rows:
		for field, value in dimensions.items():
			if value and row.meta.has_field(field):
				row.set(field, value)


def job_dimensions(job, company):
	"""{project, branch, cost_center} for a job: its Project (named after it,
	see Operations.ensure_project), Branch and Cost Center, else the
	Project's. A cost center of another company is left out."""
	values = frappe.db.get_value("Operations", job, ["project", "branch", "cost_center"], as_dict=True)
	if not values:
		return {}
	project = values.project if values.project and frappe.db.exists("Project", values.project) else None
	if not project and frappe.db.exists("Project", job):
		project = job
	cost_center = values.cost_center or (
		frappe.db.get_value("Project", project, "cost_center") if project else None
	)
	if cost_center and company and frappe.db.get_value("Cost Center", cost_center, "company") != company:
		cost_center = None
	return {"project": project, "branch": values.branch, "cost_center": cost_center}


def warn_unlinked(doc, method=None):
	"""validate: a bill with no job does not reach any job or the Cost
	variance tile. Say so; don't block. Every supplier here bills freight
	work, so it is said whatever the supplier's roles (A-03)."""
	if _skip() or doc.get("operations") or not doc.supplier:
		return
	frappe.msgprint(
		_("Not linked to a job; this cost will not show on any job or in cost variance"),
		title=_("No job"),
		indicator="orange",
	)
