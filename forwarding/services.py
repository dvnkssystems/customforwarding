# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""A job's Services (M-05, M-06, R2-23).

A job holds several Freight Activity Codes in its Services table (a door-to-door
import: Sea Import Freehand + Sea Import Clearance + Land Local Freight). Each
code has a service type, and the job's service types decide what it offers:
the Activity & Services tick-boxes, Create ▾, the Services tab and the alerts.

Which codes a job may hold:

	mode		the code's mode is the job's, or Other / empty. Transportation
			codes are trucking, which serves a shipment of any mode.
	job type	the code's Job Type is the job's, or empty.
	scope		the code's service type is allowed by the job's Scope of Work
			(its Allowed Service Types table, plus ALWAYS_ALLOWED). A scope
			with no rows, or a job with no scope, allows every type.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr

# Freight Activity Code.service_type -> the job's tick-box for it.
SERVICE_TYPE_FIELD = {
	"Freight Forwarding": "svc_freight_forwarding",
	"Customs Clearance": "svc_customs_clearance",
	"Transportation": "svc_transportation",
	"Trading": "svc_trading",
	"Warehousing": "svc_warehousing",
	"Packing & Relocation": "svc_packing_relocation",
}

# Can be added to any job, whatever its scope (M-06).
ALWAYS_ALLOWED = (
	"Warehousing",
	"Packing & Relocation",
	"Value Added Services",
	"Cargo Insurance",
	"Documentation & Certification",
)

# Service types whose codes suit any mode of shipment.
ANY_MODE = ("Transportation",)

# The job's old service flags, fetched from its Scope of Work, read only for a
# job with no services and no tick-boxes.
LEGACY_FLAGS = {
	"freight_forwarding": "Freight Forwarding",
	"custom_clearance": "Customs Clearance",
	"transport": "Transportation",
}


def code_mode(mode_of_shipment):
	"""The Freight Activity Code mode for a job's Mode of Shipment: SEA-FCL is
	Sea, Others is Other."""
	value = cstr(mode_of_shipment).strip()
	upper = value.upper()
	for mode in ("Sea", "Air", "Land"):
		if upper.startswith(mode.upper()):
			return mode
	if upper in ("OTHER", "OTHERS"):
		return "Other"
	return value


def allowed_service_types(scope_of_work):
	"""The service types a scope allows, or None when it does not restrict."""
	if not scope_of_work or not frappe.db.exists("Scope Of Work", scope_of_work):
		return None
	rows = frappe.get_cached_doc("Scope Of Work", scope_of_work).get("allowed_service_types") or []
	types = {r.service_type for r in rows if r.service_type}
	if not types:
		return None
	return types | set(ALWAYS_ALLOWED)


def code_problem(code, mode_of_shipment=None, job_type=None, allowed=None):
	"""Why a code cannot go on a job of this mode, type and scope, or ''."""
	row = frappe.get_cached_value(
		"Freight Activity Code", code, ["mode", "service_type", "job_type"], as_dict=True
	)
	if not row:
		return _("Service {0} does not exist.").format(frappe.bold(code))
	mode = code_mode(mode_of_shipment)
	if mode and row.mode and row.mode not in (mode, "Other") and row.service_type not in ANY_MODE:
		return _("{0} is a {1} service; this is a {2} job.").format(
			frappe.bold(code), row.mode, frappe.bold(mode_of_shipment)
		)
	if job_type and row.job_type and row.job_type != job_type:
		return _("{0} is for {1} jobs; this is an {2} job.").format(
			frappe.bold(code), row.job_type, frappe.bold(job_type)
		)
	if allowed is not None and row.service_type not in allowed:
		return _("{0} is {1}, which the job's Scope of Work does not include.").format(
			frappe.bold(code), frappe.bold(row.service_type or _("not typed"))
		)
	return ""


def job_codes(job):
	"""The job's Freight Activity Codes in order; its Activity Code alone for a
	job saved before it had Services."""
	codes = [cstr(r.get("activity_code")) for r in job.get("services") or [] if r.get("activity_code")]
	if not codes and job.get("activity_code"):
		codes = [job.get("activity_code")]
	return list(dict.fromkeys(codes))


def code_service_type(code):
	return frappe.get_cached_value("Freight Activity Code", code, "service_type")


def job_service_types(job):
	"""The service types the job offers work for, in a stable order: those of
	its codes and its ticked boxes (a job saved before Services may have extra
	boxes ticked by hand), within its scope. A job with neither falls back to
	the old scope flags."""
	types = [code_service_type(c) for c in job_codes(job)]
	types += [t for t, field in SERVICE_TYPE_FIELD.items() if cint(job.get(field))]
	if not any(types):
		types = [t for field, t in LEGACY_FLAGS.items() if cstr(job.get(field)) == "1"]
	allowed = allowed_service_types(job.get("scope_of_work"))
	return [t for t in dict.fromkeys(types) if t and (allowed is None or t in allowed)]


def job_services(job):
	"""The job's codes with their service type and mode, for the job page."""
	out = []
	for code in job_codes(job):
		row = frappe.get_cached_value("Freight Activity Code", code, ["mode", "service_type"], as_dict=True) or {}
		out.append({"activity_code": code, "service_type": row.get("service_type"), "mode": row.get("mode")})
	return out


# -- On the job ------------------------------------------------------------------------


def apply_services(job):
	"""Operations.validate: Services, the primary Activity Code and the
	tick-boxes kept in step, and the codes checked against the job."""
	if not job.get("services") and job.get("activity_code"):
		# A job given only an Activity Code (an older client, quote to job).
		job.append("services", {"activity_code": job.activity_code})

	codes = job_codes(job) if job.get("services") else []
	job.activity_code = codes[0] if codes else None
	job.service_list = ", ".join(codes) or None

	if job.is_new() and not job.scope_of_work and not job.flags.ignore_mandatory:
		frappe.throw(_("Choose a Scope of Work for the job."), title=_("Scope of Work missing"))

	before = job.get_doc_before_save()
	# Before Services, a job's only code was its Activity Code (job_codes).
	previous_codes = job_codes(before) if before else None
	codes_changed = job.is_new() or previous_codes != codes
	if codes_changed or any(
		before and before.get(f) != job.get(f) for f in ("mode_of_shipment", "job_type", "scope_of_work")
	):
		validate_codes(job, codes)
	if codes_changed and codes:
		tick_service_boxes(job, codes)


def validate_codes(job, codes):
	allowed = allowed_service_types(job.scope_of_work)
	problems = [p for p in (code_problem(c, job.mode_of_shipment, job.job_type, allowed) for c in codes) if p]
	if problems:
		frappe.throw("<br>".join(problems), title=_("Service not offered for this job"))


def tick_service_boxes(job, codes):
	"""Each box ticked exactly when one of the codes is of its service type."""
	types = {code_service_type(c) for c in codes}
	for service_type, field in SERVICE_TYPE_FIELD.items():
		job.set(field, 1 if service_type in types else 0)


# -- The Services picker ---------------------------------------------------------------


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def activity_code_query(doctype, txt, searchfield, start, page_len, filters):
	"""Freight Activity Codes that suit a job's mode, job type and scope.

	filters: {mode_of_shipment, job_type, scope_of_work}, each optional."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}
	mode = code_mode(filters.get("mode_of_shipment"))
	job_type = filters.get("job_type")
	allowed = allowed_service_types(filters.get("scope_of_work"))

	fac = frappe.qb.DocType("Freight Activity Code")
	query = (
		frappe.qb.from_(fac)
		.select(fac.name, fac.service_type, fac.mode)
		.where(fac.is_hidden == 0)
		.where(fac.name.like(f"%{txt}%") | fac.service_type.like(f"%{txt}%"))
		.orderby(fac.name)
		.limit(cint(page_len) or 20)
		.offset(cint(start))
	)
	if mode:
		query = query.where(
			fac.mode.isnull() | fac.mode.isin(["", "Other", mode]) | fac.service_type.isin(list(ANY_MODE))
		)
	if job_type:
		query = query.where(fac.job_type.isnull() | (fac.job_type == "") | (fac.job_type == job_type))
	if allowed is not None:
		query = query.where(fac.service_type.isin(sorted(allowed)))
	return query.run()
