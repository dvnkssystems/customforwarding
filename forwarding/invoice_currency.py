# Copyright (c) 2026, DVNKS Systems and contributors
"""An invoice or bill in a foreign currency carries a real exchange rate
(ONE Freight, 2 Nov).

An AED invoice was saved at 1.00 with only ERPNext's warning ("Conversion
rate is 1.00 …"), so the job read "Billed SAR 173" for AED 172.50. The app's
form starts the rate at 1, and ERPNext only looks a rate up when it is empty,
so it never did.

before_validate, ahead of ERPNext's own validate:
- an empty Currency takes the party's Billing Currency (else the company's),
  as ERPNext would, so the rate can be checked here;
- a foreign currency at 1 (or empty) takes the day's rate from ERPNext's own
  lookup (Currency Exchange records, else the exchange-rate service);
- with no rate to be had, the save is refused, naming the field to fill.
A rate someone typed (anything but 0 or 1) is kept.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

PARTY = {"Sales Invoice": ("Customer", "customer", "for_selling"), "Purchase Invoice": ("Supplier", "supplier", "for_buying")}


def fill_exchange_rate(doc, method=None):
	if doc.docstatus != 0 or not doc.get("company") or doc.doctype not in PARTY:
		return
	party_type, party_field, purpose = PARTY[doc.doctype]
	home = frappe.get_cached_value("Company", doc.company, "default_currency")
	if not home:
		return
	if not doc.get("currency"):
		party = doc.get(party_field)
		doc.currency = (party and frappe.db.get_value(party_type, party, "default_currency")) or home
	if doc.currency == home:
		if not flt(doc.get("conversion_rate")):
			doc.conversion_rate = 1
		return
	if flt(doc.get("conversion_rate")) not in (0, 1):
		return

	from erpnext.setup.utils import get_exchange_rate

	date = doc.get("posting_date") or nowdate()
	rate = flt(get_exchange_rate(doc.currency, home, date, purpose))
	if rate and rate != 1:
		doc.conversion_rate = rate
		return
	label = _(doc.meta.get_label("conversion_rate"))
	frappe.throw(
		_("Value missing for {0}: {1}").format(_(doc.doctype), label)
		+ "<br>"
		+ _("No exchange rate from {0} to {1} for {2} was found. Enter the {3}, or add a Currency Exchange record.").format(
			frappe.bold(doc.currency), frappe.bold(home), frappe.format(date, "Date"), label
		),
		frappe.MandatoryError,
		title=_("Exchange rate needed"),
	)
