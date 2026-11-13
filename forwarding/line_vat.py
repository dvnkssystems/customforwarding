# Copyright (c) 2026, DVNKS Systems and contributors
"""VAT per invoice line (ONE Freight, 12 Nov).

Each Sales Invoice line carries `vat_type`, one of three choices:

  15% VAT (Standard)     -> the company's Standard-rate 15% Item Tax Template
  0% VAT (Zero-rated)    -> the zero-rated "international transport of goods"
                            template (ZATCA VATEX-SA-34-1)
  No VAT (Out of scope)  -> the "outside scope of tax" template (VATEX-SA-OOS)

The choice is turned into the line's Item Tax Template before the invoice
calculates its taxes, so ERPNext works out each line's VAT and the invoice
total from it, the print shows it per line, and the KSA Compliance app puts
the template's ZATCA category and exemption reason code in the XML.

Templates are found by their ZATCA category, not their name, so every site
and company works without configuration. A line's default comes from its
charge (the Item's tax templates, the first one listed); a line the user
has not touched takes its choice from that template.
"""

import frappe
from frappe import _

STANDARD = "15% VAT (Standard)"
ZERO = "0% VAT (Zero-rated)"
OUT_OF_SCOPE = "No VAT (Out of scope)"
VAT_TYPES = (STANDARD, ZERO, OUT_OF_SCOPE)

CATEGORY_FIELD = "custom_zatca_item_tax_category"
STANDARD_CATEGORY = "Standard rate"
ZERO_CATEGORY = "Zero rated goods || The international transport of Goods"
OUT_OF_SCOPE_PREFIX = "Services outside scope of tax"


def _kind(category, rates):
	category = category or ""
	if category == STANDARD_CATEGORY and 15.0 in rates:
		return STANDARD
	if category == ZERO_CATEGORY and not any(rates):
		return ZERO
	if category.startswith(OUT_OF_SCOPE_PREFIX) and not any(rates):
		return OUT_OF_SCOPE
	return None


def templates(company):
	"""{vat type: Item Tax Template name} for the company; {} on a site without
	ZATCA categories on its templates."""
	if not company or not frappe.get_meta("Item Tax Template").has_field(CATEGORY_FIELD):
		return {}
	rows = frappe.get_all(
		"Item Tax Template",
		filters={"company": company, "disabled": 0},
		fields=["name", CATEGORY_FIELD],
		order_by="name asc",
	)
	out = {}
	for row in rows:
		rates = [
			float(r or 0)
			for r in frappe.get_all(
				"Item Tax Template Detail", filters={"parent": row.name}, pluck="tax_rate"
			)
		]
		kind = _kind(row.get(CATEGORY_FIELD), rates)
		if kind and kind not in out:
			out[kind] = row.name
	return out


def vat_type_of(template, company):
	"""The vat type a template stands for, or ''."""
	for kind, name in templates(company).items():
		if name == template:
			return kind
	return ""


@frappe.whitelist()
def options(company):
	"""For the app's invoice form: [{vat_type, template, item_tax_rate}], where
	item_tax_rate is {account: rate} as ERPNext stores it on a line."""
	from erpnext.stock.get_item_details import get_item_tax_map

	frappe.has_permission("Sales Invoice", "read", throw=True)
	out = []
	found = templates(company)
	for kind in VAT_TYPES:
		name = found.get(kind)
		if not name:
			continue
		out.append(
			{
				"vat_type": kind,
				"template": name,
				"item_tax_rate": get_item_tax_map(doc={"company": company}, tax_template=name, as_json=False),
			}
		)
	return out


def apply(doc, method=None):
	"""Sales Invoice before_validate: each line's choice -> its template, or a
	line without a choice gets the one its template stands for."""
	if not doc.meta.get_field("items") or not frappe.get_meta(doc.meta.get_field("items").options).has_field(
		"vat_type"
	):
		return
	from erpnext.stock.get_item_details import get_item_tax_map

	found = templates(doc.company)
	if not found:
		return
	by_template = {name: kind for kind, name in found.items()}
	for row in doc.get("items") or []:
		if row.get("vat_type"):
			template = found.get(row.vat_type)
			if not template:
				frappe.throw(
					_("Row {0}: there is no Item Tax Template for {1} on {2}.").format(
						row.idx, frappe.bold(row.vat_type), doc.company
					),
					title=_("VAT"),
				)
			if row.item_tax_template != template:
				row.item_tax_template = template
				row.item_tax_rate = get_item_tax_map(doc=doc, tax_template=template, as_json=True)
		elif row.get("item_tax_template") in by_template:
			row.vat_type = by_template[row.item_tax_template]


def fill_choices(doc, method=None):
	"""Sales Invoice validate: a line nobody chose for shows what its template
	is. ERPNext fills the template from the charge during its own validate,
	after before_validate has run, so this runs after it."""
	if not frappe.get_meta(doc.meta.get_field("items").options).has_field("vat_type"):
		return
	by_template = {name: kind for kind, name in templates(doc.company).items()}
	for row in doc.get("items") or []:
		if not row.get("vat_type") and row.get("item_tax_template") in by_template:
			row.vat_type = by_template[row.item_tax_template]


def set_item_default(item, vat_type, company):
	"""Make `vat_type` the Item's default for the company and list the other
	two after it. ERPNext swaps a line's template for the Item's first one when
	the Item lists templates but not the line's, so all three must be listed
	for a line to switch between them."""
	found = templates(company)
	if vat_type not in found:
		frappe.throw(_("There is no Item Tax Template for {0} on {1}.").format(vat_type, company))
	ours = [found[vat_type]] + [found[k] for k in VAT_TYPES if k != vat_type and k in found]
	doc = frappe.get_doc("Item", item)
	others = [r for r in doc.get("taxes") or [] if r.item_tax_template not in ours and not r.tax_category]
	kept = [r for r in doc.get("taxes") or [] if r.item_tax_template not in ours and r.tax_category]
	if others:
		# A blank-category template outside the three would compete with them.
		frappe.throw(
			_("{0} already has tax template {1}; remove it first.").format(item, others[0].item_tax_template)
		)
	doc.set("taxes", [])
	for name in ours:
		doc.append("taxes", {"item_tax_template": name})
	for row in kept:
		doc.append("taxes", {"item_tax_template": row.item_tax_template, "tax_category": row.tax_category,
			"valid_from": row.valid_from, "minimum_net_rate": row.minimum_net_rate,
			"maximum_net_rate": row.maximum_net_rate})
	doc.save(ignore_permissions=True)
	return [r.item_tax_template for r in doc.taxes]
