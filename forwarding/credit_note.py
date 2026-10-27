# Copyright (c) 2026, DVNKS Systems and contributors
"""Credit notes against a submitted Sales Invoice (Addendum A-11).

A credit note is ERPNext's return invoice (is_return, return_against), so
ZATCA, the ledger and the original invoice's outstanding amount treat it as
one. It keeps the original's customer, job and items; a partial credit scales
every row's rate down to the amount asked for, at the same (negative) qty —
charge items are counted in whole Nos, so a fraction of a row cannot be
returned by quantity.

ERPNext caps what can be returned by quantity, so once a credit note exists
for an invoice every row's quantity is spent: a second partial one is refused
here with that explanation rather than by ERPNext's quantity message.
"""

import frappe
from frappe import _
from frappe.utils import flt

REASON_FIELD = "custom_return_reason"  # ksa_compliance's Return/Debit Reason
TOLERANCE = 0.01


def credited_total(invoice, exclude=None):
	"""What the credit notes not cancelled against the invoice credit, as a
	positive amount."""
	filters = {"return_against": invoice, "is_return": 1, "docstatus": ["<", 2]}
	if exclude:
		filters["name"] = ["!=", exclude]
	return abs(flt(sum(frappe.get_all("Sales Invoice", filters=filters, pluck="grand_total"))))


@frappe.whitelist()
def make_credit_note(source_name, reason, amount=None):
	"""A draft credit note against source_name for its whole amount, or for
	amount (incl. VAT). Returns the draft's name; it is submitted from its form
	like any invoice."""
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

	source = frappe.get_doc("Sales Invoice", source_name)
	source.check_permission("read")
	frappe.has_permission("Sales Invoice", "create", throw=True)

	if source.docstatus != 1 or source.get("is_return"):
		frappe.throw(_("A credit note can only be made from a submitted invoice."), title=_("Not a submitted invoice"))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Enter the reason for the credit note."), title=_("Reason missing"))

	existing = frappe.get_all(
		"Sales Invoice",
		filters={"return_against": source.name, "is_return": 1, "docstatus": ["<", 2]},
		pluck="name",
	)
	if existing:
		frappe.throw(
			_(
				"{0} already has credit note {1}. Cancel it and make one for the combined amount, as an invoice's items can be credited once."
			).format(frappe.bold(source.name), ", ".join(frappe.bold(n) for n in existing)),
			title=_("Already credited"),
		)

	total = flt(source.grand_total)
	amount = flt(amount) or total
	if amount <= 0 or amount > total + TOLERANCE:
		frappe.throw(
			_("The credit can be up to {0}, the invoice's total.").format(
				frappe.bold(frappe.utils.fmt_money(total, currency=source.currency))
			),
			title=_("Amount too high"),
		)

	note = make_sales_return(source.name)
	if amount < total - TOLERANCE:
		factor = amount / total
		for row in note.items:
			rate = flt(row.rate * factor, row.precision("rate"))
			row.rate = rate
			row.price_list_rate = rate
			row.discount_percentage = 0
			row.discount_amount = 0
	note.set(REASON_FIELD, reason)
	# An invoice still owed is reduced by the credit; one already paid leaves
	# the credit on the note, to refund or allocate (ERPNext's default).
	if note.meta.has_field("update_outstanding_for_self"):
		note.update_outstanding_for_self = 0 if flt(source.outstanding_amount) >= amount - TOLERANCE else 1
	note.insert()
	return note.name


def validate(doc, method=None):
	"""A credit note says why, and together with the others never credits
	more than the invoice it returns against."""
	if not doc.get("is_return") or not doc.get("return_against") or frappe.flags.in_migrate:
		return
	if doc.meta.has_field(REASON_FIELD) and not (doc.get(REASON_FIELD) or "").strip():
		frappe.throw(_("Enter the reason for the credit note."), title=_("Reason missing"))
	original = flt(frappe.db.get_value("Sales Invoice", doc.return_against, "grand_total"))
	credited = credited_total(doc.return_against, exclude=None if doc.is_new() else doc.name) + abs(flt(doc.grand_total))
	if original and credited > original + TOLERANCE:
		frappe.throw(
			_("Credit notes against {0} would credit {1}, more than its total of {2}.").format(
				frappe.bold(doc.return_against),
				frappe.utils.fmt_money(credited, currency=doc.currency),
				frappe.utils.fmt_money(original, currency=doc.currency),
			),
			title=_("Credit too high"),
		)
