# Copyright (c) 2026, DVNKS Systems and contributors
"""Quote approval and validity (M-07, M-08).

A Quote is submittable: submitting it approves it and locks its prices
(Draft -> Submitted). Only a submitted quote whose validity has not passed
makes a job (`assert_can_make_job`, called by quote_to_job). Validity can still
be extended on a submitted quote (the field is allow_on_submit), which makes it
usable again.

`Quote` is a custom DocType with no controller class, so these run as
doc_events (hooks.py).
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate, nowdate

STATUS_BY_DOCSTATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def is_expired(validity, today=None):
	"""True once the validity date is before today (the site's day, Asia/Riyadh).
	A quote with no validity never expires."""
	return bool(validity) and getdate(validity) < getdate(today or nowdate())


PROSPECT = "Prospect"


VAT_RATE = 0.15


def validate(doc, method=None):
	set_status(doc)
	set_party(doc)
	set_mode(doc)
	set_amounts(doc)


def set_mode(doc):
	"""mode_of_shipment (the job's Mode Of Shipment list) and the older
	upper-case `mode` say the same thing (R3-45). mode_of_shipment wins when
	both are set; "SEA-FCL" style variants count as their base mode."""
	from forwarding.quote_to_job import MODES

	by_master = {v.lower(): k for k, v in MODES.items()}
	chosen = (doc.get("mode_of_shipment") or "").strip()
	if chosen:
		base = chosen.split("-")[0].strip().lower()
		doc.mode = by_master.get(base, doc.get("mode"))
	elif doc.get("mode"):
		master = MODES.get(doc.mode.strip().upper())
		if master and frappe.db.exists("Mode Of Shipment", master):
			doc.mode_of_shipment = master
	# A sea quote names a Shipping Line, an air quote an Airline; never both (R3-46).
	if doc.get("mode") == "SEA":
		doc.air_line = None
	elif doc.get("mode") == "AIR":
		doc.shipping_line = None


def set_amounts(doc):
	"""Row and quote totals, on the server so every form gets the same
	figures (R3-44; the desk script and the app did this on their own).

	Rate and Est. Cost are per unit in the row's currency; Amount, VAT and
	Est. Cost Amount are in company currency (x Ex Rate, 1 for company
	currency). A row's Qty defaults to 1. Description defaults to the Item's
	name. Est. Cost is internal: print_hide on the row, never on the print."""
	import erpnext

	company_currency = erpnext.get_default_currency()
	names = {}
	items = {r.item for r in doc.get("items") or [] if r.get("item")}
	if items:
		names = dict(frappe.get_all("Item", filters={"name": ["in", list(items)]}, fields=["name", "item_name"], as_list=True))
	sub_total = total_vat = 0.0
	for row in doc.get("items") or []:
		if row.get("item") and not (row.get("description") or "").strip():
			row.description = names.get(row.item) or row.item
		if not flt(row.get("units")):
			row.units = 1
		if not row.get("currency") or row.currency == company_currency or not flt(row.get("ex_rate")):
			row.ex_rate = 1
		ex = flt(row.ex_rate)
		row.amount = flt(flt(row.units) * flt(row.rate) * ex, 2)
		row.vat = flt(row.amount * VAT_RATE, 2) if row.get("has_vat") else 0
		row.cost_amount = flt(flt(row.units) * flt(row.get("est_cost")) * ex, 2)
		sub_total += row.amount
		total_vat += row.vat
	doc.sub_total = flt(sub_total, 2)
	doc.total_vat = flt(total_vat, 2)
	doc.total = flt(sub_total + total_vat, 2)


def set_status(doc, method=None):
	doc.status = STATUS_BY_DOCSTATUS.get(doc.docstatus, "Draft")


def converted_customer(lead):
	"""The Customer a Lead was converted to (Customer.lead_name), if any."""
	return frappe.db.get_value("Customer", {"lead_name": lead, "disabled": 0}, "name") if lead else None


def set_party(doc):
	"""Who the quote is for (R3-43): a Customer, or a prospect (a Lead) not
	yet converted. Exactly one of the two is kept; party_name is the name
	shown in lists and on the print."""
	if doc.get("quote_to") == PROSPECT:
		if not doc.get("lead"):
			frappe.throw(_("Choose the Prospect this quote is for."), frappe.MandatoryError, title=_("Customer missing"))
		doc.customer = None
		lead = frappe.db.get_value("Lead", doc.lead, ["company_name", "lead_name"], as_dict=True) or {}
		doc.party_name = lead.get("company_name") or lead.get("lead_name") or doc.lead
		return
	doc.quote_to = "Customer"
	if not doc.get("customer"):
		frappe.throw(_("Choose the Customer this quote is for."), frappe.MandatoryError, title=_("Customer missing"))
	doc.lead = None
	doc.party_name = frappe.db.get_value("Customer", doc.customer, "customer_name") or doc.customer


def job_customer(quote):
	"""The Customer a job made from the quote bills: the quote's Customer, or
	the customer its prospect was converted to. Throws for a prospect not
	converted yet."""
	if quote.get("quote_to") != PROSPECT:
		return quote.get("customer")
	customer = converted_customer(quote.get("lead"))
	if not customer:
		name = quote.get("party_name") or quote.get("lead")
		frappe.throw(
			_("Convert {0} to a customer first, then create the job.").format(frappe.bold(name)),
			title=_("Prospect not a customer yet"),
		)
	return customer


def before_submit(doc, method=None):
	"""Approving an expired quote would lock prices nobody can use."""
	if is_expired(doc.validity):
		frappe.throw(
			_("Quote {0} expired on {1}. Extend its validity before submitting it.").format(
				doc.name, formatdate(doc.validity)
			),
			title=_("Quote expired"),
		)
	doc.status = "Submitted"


def before_cancel(doc, method=None):
	doc.status = "Cancelled"


def assert_can_make_job(quote_name):
	"""Throw unless the quote is submitted and still valid."""
	quote = frappe.db.get_value("Quote", quote_name, ["name", "docstatus", "validity"], as_dict=True)
	if not quote:
		frappe.throw(_("Quote {0} not found").format(quote_name), frappe.DoesNotExistError)
	if quote.docstatus != 1:
		frappe.throw(
			_("Quote {0} is not submitted. Submit the quote before creating a job from it.").format(quote.name)
			if quote.docstatus == 0
			else _("Quote {0} is cancelled. Amend it to create a job.").format(quote.name),
			title=_("Quote not approved"),
		)
	if is_expired(quote.validity):
		frappe.throw(
			_("Quote {0} expired on {1}. Extend its validity before creating a job from it.").format(
				quote.name, formatdate(quote.validity)
			),
			title=_("Quote expired"),
		)
