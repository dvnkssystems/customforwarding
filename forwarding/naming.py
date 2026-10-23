# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Auto-generate CU-/SU- party codes (separate from the primary name series),
and the short Transportation / Custom Clearance numbers."""

import frappe
from frappe import _
from frappe.model.naming import make_autoname


def set_customer_code(doc, method=None):
	if not doc.get("customer_code"):
		doc.customer_code = make_autoname("CU-.YY.MM.-.####")


def set_supplier_code(doc, method=None):
	if not doc.get("supplier_code"):
		doc.supplier_code = make_autoname("SU-.YY.MM.-.####")


# ── Transportation / Custom Clearance numbers (M-13) ─────────────────────────


def job_code(job):
	"""The job number without its hyphens, read as branch + I/E + mode + year +
	serial: R-IM-A-26-07014 -> RIA2607014.

	A job is named {branch abbr}-{job type abbr}-{mode abbr}-{YY}-{#####}
	(Operations autoname). The branch abbreviation is kept as it is, however
	long (ALL-IM-A-26-07050 -> ALLIA2607050); the job type contributes its
	first letter (IM -> I, EX -> E); an amended job's "-1" suffix is dropped,
	so its records follow on with the next letter. A name in any other shape
	is used with its hyphens removed."""
	parts = (job or "").split("-")
	if len(parts) in (5, 6) and all(parts) and parts[3].isdigit() and parts[4].isdigit():
		branch, job_type, mode, year, serial = parts[:5]
		return f"{branch}{job_type[0]}{mode}{year}{serial}".upper()
	return (job or "").replace("-", "").upper()


def _suffixes():
	"""'', then B to Z, then BA, BB, ... -- a first record has no letter."""
	yield ""
	letters = [chr(c) for c in range(ord("B"), ord("Z") + 1)]
	yield from letters
	for first in letters:
		for second in ["A", *letters]:
			yield first + second


def service_name(doctype, prefix, job):
	"""The next free name for a job's Transportation (T) or Custom Clearance
	(C): TRIA2607014, then TRIA2607014B, TRIA2607014C, ..."""
	base = prefix + job_code(job)
	for suffix in _suffixes():
		if not frappe.db.exists(doctype, base + suffix):
			return base + suffix
	frappe.throw(_("No free {0} number left for job {1}").format(doctype, job))
