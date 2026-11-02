# Copyright (c) 2026, DVNKS Systems and contributors
"""Which payable / receivable account a party and an invoice use
(A-06 / A-09 and R3 item 14; Simran, 28 Oct and 2 Nov).

The chart has one local account per branch (Payable 20210001 Riyadh,
20210002 Jeddah, 20210003 Dammam; Receivable 15000001-3) and one per
foreign currency (Payable 20237002 USD, ...). So:

- a party billed in the company currency uses its branch's local account
  (Branch.payable_account / receivable_account); a party with no branch, or
  a branch with none set (ALL, FREELANCER), uses the company default;
- a party billed in another currency uses that currency's account;
- the account follows the party when its currency or branch changes.

Credit To is hidden on bills: it is always the supplier's account. A Sales
Invoice for a job takes the job's branch account (item 14: "Debit To from
the job's branch").
"""

import frappe
from frappe.utils import cstr

KIND = {"Supplier": "Payable", "Customer": "Receivable"}
BRANCH_FIELD = {"Payable": "payable_account", "Receivable": "receivable_account"}
COMPANY_FIELD = {"Payable": "default_payable_account", "Receivable": "default_receivable_account"}


def _usable(account, kind, company, currency=None):
	if not account:
		return False
	row = frappe.get_cached_value(
		"Account", account, ["account_type", "company", "account_currency", "is_group", "disabled"], as_dict=True
	)
	return bool(
		row
		and row.account_type == kind
		and row.company == company
		and not row.is_group
		and not row.disabled
		and (not currency or row.account_currency == currency)
	)


def branch_account(branch, kind, company, current=None):
	"""The branch's local account. A branch with none (ALL, FREELANCER), or
	no branch, keeps the party's present local account, else takes the
	company default."""
	if branch and frappe.get_meta("Branch").has_field(BRANCH_FIELD[kind]):
		account = frappe.get_cached_value("Branch", branch, BRANCH_FIELD[kind])
		if _usable(account, kind, company):
			return account
	home = frappe.get_cached_value("Company", company, "default_currency")
	if _usable(current, kind, company, home):
		return current
	account = frappe.get_cached_value("Company", company, COMPANY_FIELD[kind])
	return account if _usable(account, kind, company) else None


def currency_account(currency, kind, company, current=None):
	"""The account in a foreign currency. The party's present one is kept
	when it already fits (Receivable has two USD accounts); otherwise the
	first by account number."""
	if _usable(current, kind, company, currency):
		return current
	accounts = frappe.get_all(
		"Account",
		filters={"account_type": kind, "company": company, "account_currency": currency, "is_group": 0, "disabled": 0},
		pluck="name",
		order_by="name",
		limit=1,
	)
	return accounts[0] if accounts else None


def account_for(kind, company, currency, branch, current=None):
	home = frappe.get_cached_value("Company", company, "default_currency")
	if not currency or currency == home:
		return branch_account(branch, kind, company, current)
	return currency_account(currency, kind, company, current)


def _companies():
	return frappe.get_all("Company", pluck="name")


def set_party_accounts(doc, method=None):
	"""before_validate on Supplier and Customer, ahead of ERPNext's check
	that the account matches the Billing Currency: fill the accounts row for
	each company when the party is new, has no row, or its currency or
	branch changed. A row nobody's change touches is left as it is."""
	kind = KIND.get(doc.doctype)
	if not kind:
		return
	before = None if doc.is_new() else doc.get_doc_before_save()
	moved = before is None or any(
		cstr(before.get(field)) != cstr(doc.get(field)) for field in ("default_currency", "branch")
	)
	for company in _companies():
		row = next((r for r in doc.get("accounts") or [] if r.company == company), None)
		if row and row.account and not moved:
			continue
		account = account_for(kind, company, doc.get("default_currency"), doc.get("branch"), row and row.account)
		if not account:
			continue
		if row:
			row.account = account
		else:
			doc.append("accounts", {"company": company, "account": account})


def debit_to_from_job(doc, method=None):
	"""before_validate on Sales Invoice: an invoice for a job, in the
	company currency, books to the job's branch receivable. Credit notes keep
	their invoice's account; foreign-currency invoices keep the customer's."""
	if doc.get("is_return") or not doc.get("operations") or not doc.get("company"):
		return
	home = frappe.get_cached_value("Company", doc.company, "default_currency")
	if doc.get("currency") and doc.currency != home:
		return
	branch = frappe.db.get_value("Operations", doc.operations, "branch")
	account = branch_account(branch, "Receivable", doc.company, doc.get("debit_to"))
	if account:
		doc.debit_to = account
