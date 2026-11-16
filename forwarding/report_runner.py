# Copyright (c) 2026, DVNKS Systems and contributors
"""Run any report for the app, saved list reports included (Royal Eagle,
T-26-11-00051).

`frappe.desk.query_report.run` runs Script, Query and Custom Reports. A
"Report Builder" report (Askar - Riyadh jobs, Dammam Jobs, SHARAFU JOBS) is
not code but a saved list view: a DocType, its columns, filters and sort,
kept as JSON on the Report record. The desk opens those in its list view; the
app has one report screen, so this runs the saved list and answers in
query_report's shape ({columns, result, add_total_row}). Every other report
type goes to query_report.run unchanged.
"""

import json

import frappe
from frappe import _
from frappe.desk.query_report import run as run_query_report

# A saved list holds no paging of its own beyond page_length; the report
# screen shows every row, so this caps a runaway list rather than paging it.
MAX_ROWS = 5000
NUMERIC = ("Currency", "Float", "Int", "Percent")


@frappe.whitelist()
def run(report_name, filters=None):
	report_type = frappe.db.get_value("Report", report_name, "report_type")
	if report_type != "Report Builder":
		return run_query_report(report_name, filters=filters, ignore_prepared_report=1, are_default_filters=0)
	return run_saved_list(report_name, filters)


def run_saved_list(report_name, filters=None):
	report = frappe.get_doc("Report", report_name)
	if not report.is_permitted():
		frappe.throw(_("You don't have access to Report: {0}").format(_(report.name)), frappe.PermissionError)
	doctype = report.ref_doctype
	frappe.has_permission(doctype, "read", throw=True)

	saved = json.loads(report.json or "{}") or {}
	columns, fields = [], []
	for fieldname, field_doctype in _saved_fields(saved, doctype):
		column = _column(fieldname, field_doctype or doctype, doctype)
		if not column:
			continue
		columns.append(column)
		if (field_doctype or doctype) == doctype:
			fields.append(f"`tab{doctype}`.`{fieldname}` as `{column['fieldname']}`")
		else:
			fields.append(f"`tab{field_doctype}`.`{fieldname}` as `{column['fieldname']}`")

	rows = frappe.get_list(
		doctype,
		fields=fields or ["name"],
		filters=(saved.get("filters") or []) + _extra_filters(filters, doctype),
		order_by=saved.get("order_by") or f"`tab{doctype}`.`modified` desc",
		group_by=saved.get("group_by") or None,
		limit=MAX_ROWS,
	)
	if not columns:
		columns = [{"fieldname": "name", "label": _(doctype), "fieldtype": "Link", "options": doctype, "width": 160}]

	add_total_row = bool(saved.get("add_totals_row")) and bool(rows)
	if add_total_row:
		total = {c["fieldname"]: 0 for c in columns if c["fieldtype"] in NUMERIC}
		for row in rows:
			for key in total:
				total[key] += row.get(key) or 0
		label = next((c["fieldname"] for c in columns if c["fieldtype"] not in NUMERIC), None)
		if label:
			total[label] = _("Total")
		rows.append(total)

	return {"columns": columns, "result": rows, "add_total_row": add_total_row, "message": None}


def _saved_fields(saved, doctype):
	"""[(fieldname, doctype)] from the saved list: `fields` holds
	[fieldname, doctype] pairs; older saves keep `columns` instead."""
	pairs = saved.get("fields") or saved.get("columns") or []
	out = []
	for pair in pairs:
		if isinstance(pair, (list, tuple)) and pair:
			out.append((pair[0], pair[1] if len(pair) > 1 else doctype))
		elif isinstance(pair, dict) and pair.get("fieldname"):
			out.append((pair["fieldname"], pair.get("docfield", {}).get("parent") or doctype))
		elif isinstance(pair, str):
			out.append((pair, doctype))
	return out


STANDARD = {
	"name": ("ID", "Link"),
	"owner": ("Created By", "Link"),
	"creation": ("Created On", "Datetime"),
	"modified": ("Last Updated On", "Datetime"),
	"modified_by": ("Last Updated By", "Link"),
	"docstatus": ("Document Status", "Int"),
	"idx": ("Index", "Int"),
}


def _column(fieldname, field_doctype, doctype):
	key = fieldname if field_doctype == doctype else f"{frappe.scrub(field_doctype)}_{fieldname}"
	if fieldname in STANDARD:
		label, fieldtype = STANDARD[fieldname]
		options = (doctype if fieldname == "name" else "User") if fieldtype == "Link" else None
		return {"fieldname": key, "label": _(label), "fieldtype": fieldtype, "options": options, "width": 140}
	df = frappe.get_meta(field_doctype).get_field(fieldname)
	if not df:
		# A field removed from the DocType since the list was saved.
		return None
	label = _(df.label or fieldname)
	if field_doctype != doctype:
		label = f"{label} ({_(field_doctype)})"
	return {"fieldname": key, "label": label, "fieldtype": df.fieldtype, "options": df.options, "width": 140}


def _extra_filters(filters, doctype):
	"""Filters the report screen adds on top of the saved ones: {field: value}
	on the list's own DocType, blanks ignored."""
	if isinstance(filters, str):
		filters = json.loads(filters or "{}")
	meta = frappe.get_meta(doctype)
	out = []
	for key, value in (filters or {}).items():
		if value in (None, "", []) or not (meta.get_field(key) or key in STANDARD):
			continue
		out.append([doctype, key, "=", value])
	return out
