# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Move a Custom Clearance or Transportation one step along its status (R3-39).

The header button calls `set_status` with the next step; the page reads
`get_status` to draw the badge and the progress strip. Both return:

	{
		"doctype", "name",
		"status":      the current status,
		"steps":       the main path, in order,
		"next_status": the step the main button moves to (None at the end),
		"next_label":  that button's text ("Submit to Customs"),
		"next_needs":  [{"fieldname", "label", "fieldtype"}] the pop-up asks for,
		"extra":       [{"status", "label"}] moves for the More menu (Rejected),
	}

Custom Clearance   Draft -> Submitted to Customs -> Under Review
                   -> Duty Assessed -> Released. Rejected from any step before
                   Released; a rejected declaration is submitted again
                   ("Submit to Customs"). Submit to Customs needs Bayan No. and
                   Bayan Date (passed in `values` or already on the record).
Transportation     Planned -> In Transit -> Delivered, then Container
                   Returned from the More menu.

Only the next step (or an extra move) is accepted, so the status cannot jump
or go back. `values` sets only the fields that step asks for; anything else in
it is refused. The record is saved normally, so its own validation (Bayan No.
digits only, R3-41) still runs.
"""

import frappe
from frappe import _
from frappe.utils import nowdate

FLOWS = {
	"Custom Clearance": {
		"field": "clearance_status",
		"steps": ["Draft", "Submitted to Customs", "Under Review", "Duty Assessed", "Released"],
		"labels": {
			"Submitted to Customs": "Submit to Customs",
			"Under Review": "Mark Under Review",
			"Duty Assessed": "Mark Duty Assessed",
			"Released": "Mark Released",
			"Rejected": "Mark Rejected",
		},
		# extra status -> statuses it can be reached from
		"extra": {"Rejected": ["Draft", "Submitted to Customs", "Under Review", "Duty Assessed"]},
		# a status reached from outside the main path -> where it goes next
		"resume": {"Rejected": "Submitted to Customs"},
		"needs": {"Submitted to Customs": ["bayyan_number", "bayyan_date"]},
		# fields a step may set on top of the ones it needs
		"accepts": {"Released": ["clearance_date"], "Rejected": []},
		# filled with today when the step is reached and the field is empty
		"stamp": {"Released": "clearance_date"},
	},
	"Transportation": {
		"field": "transport_status",
		"steps": ["Planned", "In Transit", "Delivered"],
		"labels": {
			"In Transit": "Start transit",
			"Delivered": "Mark Delivered",
			"Container Returned": "Mark Container Returned",
		},
		"extra": {"Container Returned": ["Delivered"]},
		"resume": {},
		"needs": {},
		"accepts": {"In Transit": ["pickup_date"], "Delivered": ["delivery_date"]},
		"stamp": {"In Transit": "pickup_date", "Delivered": "delivery_date"},
	},
}


def _flow(doctype):
	flow = FLOWS.get(doctype)
	if not flow:
		frappe.throw(_("Status steps are only kept for {0}.").format(", ".join(FLOWS)))
	return flow


def current_status(doc, flow=None):
	flow = flow or _flow(doc.doctype)
	return doc.get(flow["field"]) or flow["steps"][0]


def next_status(flow, status):
	if status in flow["resume"]:
		return flow["resume"][status]
	steps = flow["steps"]
	if status in steps and steps.index(status) < len(steps) - 1:
		return steps[steps.index(status) + 1]
	return None


def _field(doc, fieldname):
	df = doc.meta.get_field(fieldname)
	return {"fieldname": fieldname, "label": _(df.label) if df else fieldname, "fieldtype": df.fieldtype if df else "Data"}


def describe(doc):
	flow = _flow(doc.doctype)
	status = current_status(doc, flow)
	upcoming = next_status(flow, status) if doc.docstatus < 2 else None
	return {
		"doctype": doc.doctype,
		"name": doc.name,
		"status": status,
		"steps": list(flow["steps"]),
		"next_status": upcoming,
		"next_label": _(flow["labels"][upcoming]) if upcoming else None,
		"next_needs": [_field(doc, f) for f in flow["needs"].get(upcoming, [])] if upcoming else [],
		"extra": [
			{"status": extra, "label": _(flow["labels"][extra])}
			for extra, sources in flow["extra"].items()
			if doc.docstatus < 2 and status in sources
		],
	}


@frappe.whitelist()
def get_status(doctype, name):
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return describe(doc)


@frappe.whitelist(methods=["POST"])
def set_status(doctype, name, status, values=None):
	"""Move the record to `status`, the next step or an extra move, setting
	the fields that step asks for from `values` (a dict or JSON)."""
	flow = _flow(doctype)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")
	if doc.docstatus == 2:
		frappe.throw(_("{0} {1} is cancelled.").format(_(doctype), name))

	current = current_status(doc, flow)
	allowed = {next_status(flow, current)} | {
		extra for extra, sources in flow["extra"].items() if current in sources
	}
	allowed.discard(None)
	if status not in allowed:
		if not allowed:
			message = _("{0} is already {1}; there is no next step.").format(name, frappe.bold(_(current)))
		else:
			message = _("{0} is {1}; it can only move to {2}.").format(
				name, frappe.bold(_(current)), ", ".join(frappe.bold(_(s)) for s in sorted(allowed))
			)
		frappe.throw(message, title=_("Not the next step"))

	values = frappe.parse_json(values) if values else {}
	if not isinstance(values, dict):
		frappe.throw(_("values must be an object of field: value."))
	needs = flow["needs"].get(status, [])
	accepts = set(needs) | set(flow["accepts"].get(status, []))
	unknown = sorted(set(values) - accepts)
	if unknown:
		frappe.throw(_("{0} does not set {1}.").format(_(flow["labels"][status]), ", ".join(unknown)))
	for fieldname, value in values.items():
		doc.set(fieldname, value.strip() if isinstance(value, str) else value)

	missing = [_field(doc, f)["label"] for f in needs if not doc.get(f)]
	if missing:
		frappe.throw(
			_("{0} needs {1}.").format(_(flow["labels"][status]), ", ".join(missing)),
			frappe.MandatoryError,
			title=_("Details missing"),
		)

	doc.set(flow["field"], status)
	stamp = flow["stamp"].get(status)
	if stamp and doc.meta.has_field(stamp) and not doc.get(stamp):
		doc.set(stamp, nowdate())
	doc.save()
	return describe(doc)
