# Copyright (c) 2026, DVNKS Systems and contributors
"""Quote lists match the job's (R3-45, R3-46).

1. Inco Terms: the full-name records ("DELIVERED AT PLACE") are merged into
   their codes ("DAP") with Rename > Merge, so every job and quote shows the
   code. DELIVERED EX SHIP has no code record and is renamed DES.
2. Quote POL / POD become Links to Port: a name that matches one Port for the
   quote's mode (as Create Job matches them) is replaced by that Port; the
   rest is cleared and kept in the quote's "Old Values Not Matched" note.
3. Quote Shipping Terms (now Incoterms, a Link to Inco Terms): C&F -> CFR,
   DDU -> DAP; anything else that names no record goes to the note.
4. Quote Carrier (free text) -> Shipping Line on a sea quote when it names one,
   Airline on an air quote; otherwise it stays in the hidden Carrier field and
   the note.
5. mode_of_shipment is filled from mode.

Quote rows are written directly; the quotes are not saved.
"""

import frappe

from forwarding.patches.v1_0.r3_quote_customer import sync_quote_fixture

INCOTERM_CODES = {
	"DELIVERED AT PLACE": "DAP",
	"DELIVERED AT TERMINAL": "DAT",
	"COST AND FREIGHT": "CFR",
	"COST INSURANCE AND FREIGHT": "CIF",
	"CARRIAGE PAID TO": "CPT",
	"CARRIAGE INSURANCE PAID TO": "CIP",
	"EX WORKS": "EXW",
	"DELIVERED EX SHIP": "DES",
}
OLD_QUOTE_TERMS = {"C&F": "CFR", "DDU": "DAP"}


def execute():
	sync_quote_fixture()
	merge_incoterms()
	for quote in frappe.get_all(
		"Quote", fields=["name", "mode", "pol", "pod", "shipping_terms", "carrier", "unmatched_note", "mode_of_shipment"]
	):
		migrate_quote(quote)


def merge_incoterms():
	for full, code in INCOTERM_CODES.items():
		if not frappe.db.exists("Inco Terms", full):
			continue
		merge = bool(frappe.db.exists("Inco Terms", code))
		frappe.rename_doc("Inco Terms", full, code, merge=merge, force=True, show_alert=False)
		if not merge:
			frappe.db.set_value("Inco Terms", code, {"inco_term": code, "inco_term_name": f"{code} ({full})"})


def migrate_quote(quote):
	from forwarding.quote_to_job import MODES, _match, _resolve_port

	mode = MODES.get((quote.mode or "").strip().upper())
	values, notes = {}, []

	for field, label in (("pol", "POL"), ("pod", "POD")):
		text = (quote.get(field) or "").strip()
		if not text or frappe.db.exists("Port", text):
			continue
		port = _resolve_port(text, mode)
		values[field] = port
		if not port:
			notes.append(f"{label}: {text}")

	terms = (quote.shipping_terms or "").strip()
	if terms and not frappe.db.exists("Inco Terms", terms):
		code = OLD_QUOTE_TERMS.get(terms.upper()) or INCOTERM_CODES.get(terms.upper())
		values["shipping_terms"] = code if code and frappe.db.exists("Inco Terms", code) else None
		if not values["shipping_terms"]:
			notes.append(f"Incoterms: {terms}")

	carrier = (quote.carrier or "").strip()
	if carrier:
		line = _match("Shipping Line", carrier) if mode == "Sea" else None
		if line:
			values["shipping_line"] = line
		elif mode == "Air":
			values["air_line"] = carrier
		else:
			notes.append(f"Carrier: {carrier}")

	if mode and not quote.mode_of_shipment and frappe.db.exists("Mode Of Shipment", mode):
		values["mode_of_shipment"] = mode

	if notes:
		values["unmatched_note"] = "\n".join(filter(None, [quote.unmatched_note, *notes]))
	if values:
		frappe.db.set_value("Quote", quote.name, values, update_modified=False)
