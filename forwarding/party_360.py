# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Helpers shared by the Customer 360 and Supplier 360 APIs.

Both pages read a party (Customer or Supplier) and the records around it, and
cache the payload per party for everyone. These are the parts that do not
depend on which kind of party it is: the company the money is counted in,
the party's Contacts and Addresses, the Document Table rows of a set of
records, files attached to the party, outstanding amounts in company
currency, the per-user list filter and the banner loop.
"""

import frappe
from frappe.contacts.doctype.address.address import render_address
from frappe.utils import cstr, flt, fmt_money, getdate

CONTACT_FIELDS = ["name", "full_name", "email_id", "mobile_no", "is_primary_contact"]
ADDRESS_FIELDS = [
	"name",
	"address_title",
	"address_type",
	"address_line1",
	"city",
	"country",
	"is_primary_address",
]


def default_company():
	"""The site's default company. Not the user's: the payload is shared."""
	return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name", order_by="creation asc"
	)


def for_user(payload, header_key, guarded):
	"""Drop the lists the current user may not read. Works on a copy.

	guarded maps a payload list to the DocType a user must be able to read
	to see it; the header's primary contact and address follow Contact and
	Address read permission."""
	payload = dict(payload)
	for key, doctype in guarded.items():
		if not frappe.has_permission(doctype, "read"):
			payload[key] = []
	header = dict(payload[header_key])
	if not frappe.has_permission("Contact", "read"):
		header["primary_contact"] = None
	if not frappe.has_permission("Address", "read"):
		header["primary_address"] = None
	payload[header_key] = header
	return payload


# -- Contacts and addresses -------------------------------------------------------


def linked_party_records(doctype, party_type, party, fields, primary_field, limit):
	"""Contacts or Addresses linked to the party, primary first."""
	return frappe.get_all(
		doctype,
		filters=[
			["Dynamic Link", "link_doctype", "=", party_type],
			["Dynamic Link", "link_name", "=", party],
			["Dynamic Link", "parenttype", "=", doctype],
		],
		fields=fields,
		order_by=f"`tab{doctype}`.{primary_field} desc, `tab{doctype}`.creation desc",
		limit=limit,
	)


def _primary(doc_link, rows, primary_field):
	if doc_link:
		return doc_link
	for row in rows:
		if row.get(primary_field):
			return row.name
	return rows[0].name if rows else None


def primary_contact(doc_link, contacts):
	"""{name, full_name, email_id, mobile_no} of the party's primary contact:
	the one the party links to, else the flagged one, else the first."""
	name = _primary(doc_link, contacts, "is_primary_contact")
	if not name:
		return None
	row = next((c for c in contacts if c.name == name), None) or frappe.db.get_value(
		"Contact", name, CONTACT_FIELDS, as_dict=True
	)
	return {k: row.get(k) for k in ("name", "full_name", "email_id", "mobile_no")} if row else None


def primary_address(doc_link, addresses):
	name = _primary(doc_link, addresses, "is_primary_address")
	if not name or not frappe.db.exists("Address", name):
		return None
	return {"name": name, "address_display": render_address(name, check_permissions=False)}


# -- Money -------------------------------------------------------------------------


def base_outstanding(row, currency):
	"""An invoice's outstanding_amount (party account currency) in company
	currency. Needs party_account_currency and conversion_rate on the row."""
	if row.party_account_currency and row.party_account_currency != currency:
		return flt(row.outstanding_amount) * flt(row.conversion_rate or 1)
	return flt(row.outstanding_amount)


def is_overdue(row, today):
	"""A submitted invoice with money owed past its due date."""
	return bool(
		row.docstatus == 1 and flt(row.outstanding_amount) > 0 and row.due_date and getdate(row.due_date) < today
	)


# -- Documents ---------------------------------------------------------------------


def document_rows(parents):
	"""Document Table rows of parents, a list of (doctype, name), in the
	order of parents and then row idx."""
	if not parents:
		return []
	table = frappe.qb.DocType("Document Table")
	found = (
		frappe.qb.from_(table)
		.select(
			table.name,
			table.parent,
			table.parenttype,
			table.document,
			table.stage,
			table.received,
			table.date,
			table.attach,
			table.idx,
		)
		.where(
			table.parent.isin(list({n for _dt, n in parents}))
			& table.parenttype.isin(list({dt for dt, _n in parents}))
		)
		.run(as_dict=True)
	)
	order = {p: i for i, p in enumerate(parents)}
	# The two isin()s can match a (doctype, name) pair that is not a parent.
	found = [r for r in found if (r.parenttype, r.parent) in order]
	found.sort(key=lambda r: (order[(r.parenttype, r.parent)], r.idx))
	return [
		{
			"document": r.document,
			"stage": r.stage,
			"received": 1 if cstr(r.received).strip() == "Yes" else 0,
			"date": r.date,
			"attach": r.attach,
			"source_doctype": r.parenttype,
			"source_name": r.parent,
			"row_name": r.name,
		}
		for r in found
	]


def attached_file_rows(doctype, name):
	"""Files attached to the record, as document rows (always received)."""
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name, "is_folder": 0},
		fields=["name", "file_name", "file_url", "creation"],
		order_by="creation desc",
	)
	return [
		{
			"document": f.file_name,
			"stage": None,
			"received": 1,
			"date": getdate(f.creation),
			"attach": f.file_url,
			"source_doctype": doctype,
			"source_name": name,
			"row_name": f.name,
		}
		for f in files
	]


# -- Banners -------------------------------------------------------------------------


def money(amount, ctx):
	"""amount in ctx["currency"], for banner messages."""
	return fmt_money(flt(amount), precision=2, currency=ctx.get("currency"))



def evaluate_banners(banners, ctx, label):
	"""[{code, colour, message, action}] for every banner whose condition
	holds. label names the page in the error log."""
	out = []
	for banner in banners:
		try:
			if not banner["condition"](ctx):
				continue
			message = banner["message"](ctx)
		except Exception:
			# One broken banner must not take the page down.
			frappe.log_error(title=f"{label} banner {banner['code']} failed")
			continue
		out.append(
			{
				"code": banner["code"],
				"colour": banner["colour"],
				"message": message,
				"action": banner["action"],
			}
		)
	return out
