# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""A job's Services (M-05, M-06, R2-23).

A job holds several Freight Activity Codes in its Services table (a door-to-door
import: Sea Freight Import + Sea Import Clearance + Land Local Freight). Each
code has a service type, and the job's service types decide what it offers:
the Activity & Services tick-boxes, Create ▾, the Services tab and the alerts.

Which codes a job may hold:

	mode		the code's mode is the job's, or Other / empty. Transportation
			codes are trucking, which serves a shipment of any mode.
	job type	the code's Job Type is the job's, or empty.
	scope		the code's service type is allowed by one of the job's Scopes
			of Work (their Allowed Service Types tables). A job with no
			scope, or one of whose scopes has no rows, allows every type.

A job holds several Scopes of Work (its Scope Of Work table, Job Scope Of
Work); the first is copied to the old scope_of_work field, which job numbers,
prints and reports read. A service type no chosen scope covers appears
nowhere on the job: there is no longer a list of types every scope allows
(the old ALWAYS_ALLOWED); the Other Services scope covers them instead.
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

# Every service type, in the order the job page lists them (Scope Of Work
# Service Type.service_type).
SERVICE_TYPES = (
	"Freight Forwarding",
	"Customs Clearance",
	"Transportation",
	"Warehousing",
	"Packing & Relocation",
	"Value Added Services",
	"Cargo Insurance",
	"Documentation & Certification",
	"Trading",
	"Other",
)

# The records a job's work is done in, by the service type each serves. One
# that is live (not cancelled) keeps its type in the job's scopes.
RECORD_SERVICE_TYPE = {
	"Freight": "Freight Forwarding",
	"Custom Clearance": "Customs Clearance",
	"Transportation": "Transportation",
}

# The job's old service flags, set from its scopes, and the type each stands for.
SCOPE_FLAGS = (
	("freight_forwarding", "Freight Forwarding"),
	("custom_clearance", "Customs Clearance"),
	("transport", "Transportation"),
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


def scope_names(scopes):
	"""Scope names from a name, a list of names or rows, or their JSON."""
	if not scopes:
		return []
	if isinstance(scopes, str):
		scopes = frappe.parse_json(scopes) if scopes.lstrip().startswith("[") else [scopes]
	names = [cstr(s.get("scope_of_work") if hasattr(s, "get") else s).strip() for s in scopes]
	return list(dict.fromkeys(n for n in names if n))


def allowed_service_types(scopes):
	"""The service types the scopes allow between them, or None when they do
	not restrict: no scope, or one with no Allowed Service Types rows.

	scopes: a scope name, or a list of them (as job_scopes gives)."""
	names = [n for n in scope_names(scopes) if frappe.db.exists("Scope Of Work", n)]
	if not names:
		return None
	types = set()
	for name in names:
		rows = frappe.get_cached_doc("Scope Of Work", name).get("allowed_service_types") or []
		scope_types = {r.service_type for r in rows if r.service_type}
		if not scope_types:
			return None
		types |= scope_types
	return types


def ordered(types):
	"""Service types in SERVICE_TYPES order, any unknown ones after."""
	return sorted(types, key=lambda t: (SERVICE_TYPES.index(t) if t in SERVICE_TYPES else len(SERVICE_TYPES), t))


@frappe.whitelist()
def scope_service_types(scopes=None):
	"""The service types a job with these scopes may hold, for the New Job
	wizard and the job form while scopes are being chosen: a list, or None
	when every type is allowed."""
	frappe.has_permission("Operations", "read", throw=True)
	allowed = allowed_service_types(scope_names(scopes))
	return None if allowed is None else ordered(allowed)


def job_scopes(job):
	"""The job's Scopes of Work in order; its scope_of_work alone for a job
	saved before it had several."""
	names = scope_names(job.get("scopes_of_work") or [])
	if not names and job.get("scope_of_work"):
		names = [job.get("scope_of_work")]
	return names


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
		return _("{0} is {1}, which none of the job's Scopes of Work include.").format(
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
	allowed = allowed_service_types(job_scopes(job))
	return [t for t in dict.fromkeys(types) if t and (allowed is None or t in allowed)]


def job_allowed_service_types(job):
	"""The service types the job's scopes allow, in order, or None for all."""
	allowed = allowed_service_types(job_scopes(job))
	return None if allowed is None else ordered(allowed)


def job_services(job):
	"""The job's codes with their service type and mode, for the job page;
	a code its scopes no longer cover is left out."""
	allowed = allowed_service_types(job_scopes(job))
	out = []
	for code in job_codes(job):
		row = frappe.get_cached_value("Freight Activity Code", code, ["mode", "service_type"], as_dict=True) or {}
		if allowed is not None and row.get("service_type") not in allowed:
			continue
		out.append({"activity_code": code, "service_type": row.get("service_type"), "mode": row.get("mode")})
	return out


# -- Services a job starts with (R3-23) -----------------------------------------------

# The service types a scope brings with it on its own. The others a scope may
# allow (Warehousing, Trading, Insurance...) are offered, not assumed: the
# user adds them.
CORE_SERVICE_TYPES = ("Freight Forwarding", "Customs Clearance", "Transportation")


def default_codes(job_type=None, mode_of_shipment=None, scopes=None):
	"""The Freight Activity Codes a job of this type, mode and scope starts
	with: one per core service type its scopes allow, the best fit for the
	mode and job type (an exact job type before a blank one; for several
	exact ones, the plain '<Mode> Freight <Job Type>' code). A job whose
	scopes do not restrict service types gets none -- there is nothing to go
	on."""
	names = scope_names(scopes)
	allowed = allowed_service_types(names)
	if allowed is None:
		return []
	mode = code_mode(mode_of_shipment)
	rows = frappe.get_all(
		"Freight Activity Code",
		filters={"is_hidden": 0, "service_type": ["in", [t for t in CORE_SERVICE_TYPES if t in allowed]]},
		fields=["name", "service_type", "mode", "job_type"],
		order_by="name asc",
	)
	plain = f"{mode} Freight {job_type}" if mode and job_type else None
	out = []
	for service_type in CORE_SERVICE_TYPES:
		if service_type not in allowed:
			continue
		fits = [
			r
			for r in rows
			if r.service_type == service_type and not code_problem(r.name, mode_of_shipment, job_type, allowed)
		]
		if not fits:
			continue
		fits.sort(
			key=lambda r: (
				0 if job_type and r.job_type == job_type else 1,
				0 if mode and r.mode == mode else 1,
				0 if plain and r.name == plain else 1,
				r.name,
			)
		)
		out.append(fits[0].name)
	return out


@frappe.whitelist()
def default_services(job_type=None, mode_of_shipment=None, scopes_of_work=None):
	"""default_codes for the job form and the New Job wizard (R3-23, R3-34):
	a list of Freight Activity Code names."""
	frappe.has_permission("Operations", "read", throw=True)
	return default_codes(job_type, mode_of_shipment, scopes_of_work)


# -- On the job ------------------------------------------------------------------------


def apply_services(job):
	"""Operations.validate: Services, the primary Activity Code and the
	tick-boxes kept in step, and the codes checked against the job."""
	if not job.get("services") and job.get("activity_code"):
		# A job given only an Activity Code (an older client, quote to job).
		job.append("services", {"activity_code": job.activity_code})
	if job.is_new() and not job.get("services") and not job.flags.skip_default_services:
		# A new job with none chosen starts with what its type, mode and
		# scope call for (R3-23); the user can remove or add after.
		for code in default_codes(job.job_type, job.mode_of_shipment, job_scopes(job)):
			job.append("services", {"activity_code": code})

	codes = job_codes(job) if job.get("services") else []
	job.activity_code = codes[0] if codes else None
	job.service_list = ", ".join(codes) or None

	before = job.get_doc_before_save()
	sync_scopes(job, before)
	if job.is_new() and not job_scopes(job) and not job.flags.ignore_mandatory:
		frappe.throw(_("Choose a Scope of Work for the job."), title=_("Scope of Work missing"))

	# Before Services, a job's only code was its Activity Code (job_codes).
	previous_codes = job_codes(before) if before else None
	codes_changed = job.is_new() or previous_codes != codes
	scopes_changed = bool(before) and job_scopes(before) != job_scopes(job)
	if codes_changed or scopes_changed or any(
		before and before.get(f) != job.get(f) for f in ("mode_of_shipment", "job_type")
	):
		validate_codes(job, codes)
	if scopes_changed:
		validate_linked_records(job, had_scopes=bool(job_scopes(before)))
	if codes_changed and codes:
		tick_service_boxes(job, codes)


def sync_scopes(job, before=None):
	"""The Scope Of Work table and the old scope_of_work field kept in step.

	A job given only scope_of_work (an older client, a Movement Type's fetch,
	a quote) gets it as its first row, unless it is a saved job whose rows
	were just all removed. scope_of_work is then the first row, and the old
	flags and its abbreviation follow."""
	names = scope_names(job.get("scopes_of_work") or [])
	had_rows = bool(before and scope_names(before.get("scopes_of_work") or []))
	if not names and job.get("scope_of_work") and not had_rows:
		names = [job.scope_of_work]
	rows = [cstr(r.get("scope_of_work")).strip() for r in job.get("scopes_of_work") or []]
	if rows != names:
		# One row per scope, in the order chosen.
		job.set("scopes_of_work", [{"scope_of_work": n} for n in names])
	job.scope_of_work = names[0] if names else None
	job.sow_abb = frappe.db.get_value("Scope Of Work", job.scope_of_work, "abbreviation") if names else None
	set_scope_flags(job, names)


def set_scope_flags(job, names):
	"""freight_forwarding / custom_clearance / transport ("1" or "0"), which
	the job form's detail sections read, from all the job's scopes."""
	if not names:
		return
	allowed = allowed_service_types(names)
	for field, service_type in SCOPE_FLAGS:
		if allowed is None:
			on = any(cint(frappe.db.get_value("Scope Of Work", n, field)) for n in names)
		else:
			on = service_type in allowed
		job.set(field, "1" if on else "0")


def validate_linked_records(job, had_scopes=False):
	"""A scope cannot be removed while a live record does work it covered:
	a Custom Clearance, Transportation or Freight not cancelled whose service
	type the remaining scopes leave out.

	No scope at all means "unrestricted" for a job that never had one, but
	removing a job's last scope covers nothing (A-01: 07048 dropped its only
	scope while CJIS2607048 was live, and saved)."""
	remaining = job_scopes(job)
	allowed = allowed_service_types(remaining)
	if allowed is None and had_scopes and not remaining:
		allowed = set()
	if allowed is None:
		return
	problems = []
	for doctype, service_type in RECORD_SERVICE_TYPE.items():
		if service_type in allowed:
			continue
		for name in frappe.get_all(
			doctype, filters={"operations": job.name, "docstatus": ["<", 2]}, pluck="name", order_by="name"
		):
			problems.append(
				_("{0} {1} is {2}, which the remaining Scopes of Work do not include.").format(
					_(doctype), frappe.bold(name), frappe.bold(_(service_type))
				)
			)
	if problems:
		problems.append(_("Cancel it, or keep a scope that covers it."))
		frappe.throw("<br>".join(problems), title=_("Scope of Work still in use"))


def validate_codes(job, codes):
	allowed = allowed_service_types(job_scopes(job))
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

	filters: {mode_of_shipment, job_type, scopes_of_work (a list of scope
	names, or their JSON), scope_of_work (one, from an older client),
	exclude (codes already on the job, a list or its JSON: they drop out of
	the list, R3-25)}, each optional."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}
	mode = code_mode(filters.get("mode_of_shipment"))
	job_type = filters.get("job_type")
	allowed = allowed_service_types(scope_names(filters.get("scopes_of_work")) or filters.get("scope_of_work"))

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
	exclude = filters.get("exclude")
	if isinstance(exclude, str):
		exclude = frappe.parse_json(exclude) if exclude.lstrip().startswith("[") else [exclude]
	exclude = [cstr(c) for c in exclude or [] if c]
	if exclude:
		query = query.where(fac.name.notin(exclude))
	return query.run()
