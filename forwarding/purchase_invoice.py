# Copyright (c) 2026, DVNKS Systems and contributors
"""Purchase Invoice rules for freight costs (Phase 2 spec §5.6).

A bill counts towards a job (the job's costs, the supplier's Cost variance)
through Purchase Invoice.operations. A bill from a freight supplier with no
job is allowed but warned about, and a bill with a job takes the job's
Project and Cost Center, so its GL entries land on the job as the Sales
Invoice's do (there a desk client script copies operations into project).
"""

import frappe
from frappe import _

# Supplier role tick-boxes (forwarding.api.supplier_360.SUPPLIER_ROLES).
ROLE_FIELDS = (
	"is_transporter",
	"is_handling_agent",
	"is_broker",
	"is_shipping_line",
	"is_airline",
	"is_overseas_agent",
)


def _skip():
	return frappe.flags.in_import or frappe.flags.in_migrate or frappe.flags.in_patch or frappe.flags.in_install


def fill_from_job(doc, method=None):
	"""before_validate: project and cost_center from the job, on the bill and
	on each item, wherever they are empty.

	A cost center equal to the company's default counts as empty too: Frappe
	(and the desk form) fills every new item row with the company default
	before any hook runs, so it cannot be told apart from a choice. Any other
	cost center, and any project already set, is the user's and is kept."""
	if not doc.get("operations"):
		return
	project, cost_center = job_dimensions(doc.operations, doc.company)
	default_cc = frappe.get_cached_value("Company", doc.company, "cost_center") if doc.company else None
	for row in [doc, *(doc.get("items") or [])]:
		if project and not row.get("project"):
			row.project = project
		if cost_center and row.get("cost_center") in (None, "", default_cc):
			row.cost_center = cost_center


def job_dimensions(job, company):
	"""(project, cost_center) for a job: its Project (named after it, see
	Operations.ensure_project) and its Cost Center, else the Project's. A
	cost center of another company is left out."""
	values = frappe.db.get_value("Operations", job, ["project", "cost_center"], as_dict=True)
	if not values:
		return None, None
	project = values.project if values.project and frappe.db.exists("Project", values.project) else None
	if not project and frappe.db.exists("Project", job):
		project = job
	cost_center = values.cost_center or (
		frappe.db.get_value("Project", project, "cost_center") if project else None
	)
	if cost_center and company and frappe.db.get_value("Cost Center", cost_center, "company") != company:
		cost_center = None
	return project, cost_center


def warn_unlinked(doc, method=None):
	"""validate: a bill from a supplier with a freight role and no job does
	not reach any job or the Cost variance tile. Say so; don't block."""
	if _skip() or doc.get("operations") or not doc.supplier:
		return
	roles = frappe.db.get_value("Supplier", doc.supplier, list(ROLE_FIELDS), as_dict=True) or {}
	if any(roles.values()):
		frappe.msgprint(
			_("Not linked to a job; this cost will not show on any job or in cost variance"),
			title=_("No job"),
			indicator="orange",
		)
