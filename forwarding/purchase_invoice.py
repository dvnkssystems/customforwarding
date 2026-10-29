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
		# With no job, the Branch is the Cost Center's (A-02 retest).
		for row in rows:
			if row.meta.has_field("branch") and not row.get("branch"):
				row.branch = branch_for_cost_center(row.get("cost_center") or doc.get("cost_center"))
		return
	dimensions = job_dimensions(doc.operations, doc.company)
	for row in rows:
		for field, value in dimensions.items():
			if value and row.meta.has_field(field):
				row.set(field, value)


def branch_for_cost_center(cost_center):
	"""The Branch whose Cost Center this is (Branch.cost_center), when exactly
	one branch has it; else None."""
	if not cost_center:
		return None
	branches = frappe.get_all("Branch", filters={"cost_center": cost_center}, pluck="name", limit=2)
	return branches[0] if len(branches) == 1 else None


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


def due_from_credit_period(doc, method=None):
	"""before_validate: a draft bill's due date is its posting date plus the
	party's Credit Period (A-15), so it is not Overdue the day it is raised.

	Only a due date left at the posting date (the default) is moved; one the
	user set later is kept. A party with a Payment Terms Template, or no
	Credit Period, is left to ERPNext."""
	from frappe.utils import add_days, cint, getdate

	if doc.docstatus != 0 or doc.get("is_return") or doc.get("payment_terms_template"):
		return
	party_type = "Customer" if doc.doctype == "Sales Invoice" else "Supplier"
	party = doc.get(party_type.lower())
	period = frappe.db.get_value(party_type, party, "credit_period") if party else None
	days = cint(str(period or "").split(" ")[0])
	posting = doc.get("posting_date")
	if not days or not posting:
		return
	if doc.get("due_date") and getdate(doc.due_date) > getdate(posting):
		return
	doc.due_date = add_days(posting, days)
	# ERPNext rebuilds the schedule from the due date when it is empty.
	doc.set("payment_schedule", [])


def branch_for_naming(doc, method=None):
	"""before_insert: the bill's Branch from its job, and that branch's
	abbreviation in b_abb, before the name is made — the series is
	PI-.{b_abb}.-.YY.-.##### (A-19: "PI--00001" had no branch). The job's
	Project and Cost Center follow in fill_from_job."""
	if doc.get("operations") and not doc.get("branch"):
		doc.branch = frappe.db.get_value("Operations", doc.operations, "branch")
	if not doc.get("operations") and not doc.get("branch") and doc.meta.has_field("branch"):
		doc.branch = branch_for_cost_center(doc.get("cost_center"))
	if doc.get("branch") and doc.meta.has_field("b_abb"):
		doc.b_abb = frappe.db.get_value("Branch", doc.branch, "abbreviation") or doc.get("b_abb")


def payment_branch_from_bill(doc, method=None):
	"""before_validate: a payment against bills takes their Branch (A-20),
	which is their job's; one left empty only. The first referenced invoice
	with a branch decides."""
	if doc.get("branch") or not doc.meta.has_field("branch"):
		return
	for ref in doc.get("references") or []:
		if ref.reference_doctype in ("Sales Invoice", "Purchase Invoice") and ref.reference_name:
			branch = frappe.db.get_value(ref.reference_doctype, ref.reference_name, "branch")
			if branch:
				doc.branch = branch
				return
