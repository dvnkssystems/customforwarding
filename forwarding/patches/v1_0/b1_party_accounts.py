# Copyright (c) 2026, DVNKS Systems and contributors
"""Payable and receivable accounts for every party (A-06 / A-09, R3 item 14;
Simran, 2 Nov).

- Company defaults: Payable 20210001 Riyadh, Receivable 15000001 Riyadh.
- Branch accounts: RIYADH, JEDDAH and DAMMAM get their local Payable
  (20210001-3) and Receivable (15000001-3). ALL and FREELANCER get none, so
  their parties use the company default (Riyadh).
- All suppliers and customers: an empty Billing Currency becomes the
  currency of the account the party already has, else the company's; then
  the accounts row follows forwarding.party_accounts.account_for.

Accounts are found by number in each company, so a site whose chart lacks
them is skipped. Runs before migrate syncs custom fields, so the Branch
fields are synced here first.
"""

import os

import frappe
from frappe.modules.utils import sync_customizations_for_doctype

from forwarding.party_accounts import account_for

COMPANY_DEFAULTS = {"default_payable_account": "20210001", "default_receivable_account": "15000001"}
BRANCH_ACCOUNTS = {
	"RIYADH": ("20210001", "15000001"),
	"JEDDAH": ("20210002", "15000002"),
	"DAMMAM": ("20210003", "15000003"),
}
KIND = {"Supplier": "Payable", "Customer": "Receivable"}


def execute():
	sync_branch_fields()
	frappe.clear_cache(doctype="Branch")
	for company in frappe.get_all("Company", pluck="name"):
		set_company_defaults(company)
		set_branch_accounts(company)
		for doctype in KIND:
			set_party_rows(doctype, company)
	frappe.clear_cache()


def sync_branch_fields():
	folder = frappe.get_app_path("forwarding", "forwarding", "custom")
	with open(os.path.join(folder, "branch.json")) as f:
		sync_customizations_for_doctype(frappe.parse_json(f.read()), folder, "branch.json")


def by_number(number, company):
	return frappe.db.get_value("Account", {"account_number": number, "company": company, "is_group": 0}, "name")


def set_company_defaults(company):
	for field, number in COMPANY_DEFAULTS.items():
		account = by_number(number, company)
		if account and not frappe.db.get_value("Company", company, field):
			frappe.db.set_value("Company", company, field, account, update_modified=False)


def set_branch_accounts(company):
	for branch, numbers in BRANCH_ACCOUNTS.items():
		if not frappe.db.exists("Branch", branch):
			continue
		for field, number in zip(("payable_account", "receivable_account"), numbers):
			account = by_number(number, company)
			if account and not frappe.db.get_value("Branch", branch, field):
				frappe.db.set_value("Branch", branch, field, account, update_modified=False)


def set_party_rows(doctype, company):
	kind = KIND[doctype]
	home = frappe.db.get_value("Company", company, "default_currency")
	rows = {
		r.parent: r
		for r in frappe.get_all(
			"Party Account", filters={"parenttype": doctype, "company": company}, fields=["name", "parent", "account"]
		)
	}
	for party in frappe.get_all(doctype, fields=["name", "default_currency", "branch"]):
		row = rows.get(party.name)
		current = row.account if row else None
		currency = party.default_currency
		if not currency:
			currency = (frappe.db.get_value("Account", current, "account_currency") if current else None) or home
			frappe.db.set_value(doctype, party.name, "default_currency", currency, update_modified=False)
		account = account_for(kind, company, currency, party.branch, current)
		if not account or account == current:
			continue
		if row:
			frappe.db.set_value("Party Account", row.name, "account", account, update_modified=False)
		else:
			frappe.get_doc(
				{
					"doctype": "Party Account",
					"parenttype": doctype,
					"parentfield": "accounts",
					"parent": party.name,
					"company": company,
					"account": account,
					"idx": 1,
				}
			).db_insert()
