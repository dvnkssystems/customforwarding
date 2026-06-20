# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FreightVoucher(Document):
	RECEIVE = ("BCV", "CCV")
	PAY = ("BPV", "CPV")
	JOURNAL = ("N", "TV", "IV")

	def before_save(self):
		self.local_amount = (self.amount or 0) * (self.exchange_rate or 1)
		if self.party_type == "Customer":
			self.party = self.customer or self.party
		elif self.party_type == "Supplier":
			self.party = self.supplier or self.party

	def on_submit(self):
		if self.voucher_type in self.RECEIVE + self.PAY:
			self._make_payment_entry()
		elif self.voucher_type in self.JOURNAL:
			self._make_journal_entry()

	def on_cancel(self):
		self._cancel_internal()

	def _make_payment_entry(self):
		from erpnext.accounts.party import get_party_account
		receive = self.voucher_type in self.RECEIVE
		party_type = "Customer" if receive else "Supplier"
		party = self.customer if receive else self.supplier
		if not party:
			frappe.throw(frappe._("Set the {0} for this voucher").format(party_type))
		if not self.bank_cash_account:
			frappe.throw(frappe._("Set the Bank/Cash Account"))

		party_account = get_party_account(party_type, party, self.company)
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Receive" if receive else "Pay"
		pe.company = self.company
		pe.posting_date = self.posting_date
		pe.party_type = party_type
		pe.party = party
		pe.paid_amount = self.amount
		pe.received_amount = self.amount
		pe.source_exchange_rate = self.exchange_rate or 1
		pe.target_exchange_rate = self.exchange_rate or 1
		if receive:
			pe.paid_from = party_account
			pe.paid_to = self.bank_cash_account
		else:
			pe.paid_from = self.bank_cash_account
			pe.paid_to = party_account
		pe.reference_no = self.reference_no or self.name
		pe.reference_date = self.reference_date or self.posting_date
		pe.flags.ignore_permissions = True
		pe.insert()
		pe.submit()
		self.db_set("internal_voucher_type", "Payment Entry")
		self.db_set("internal_voucher", pe.name)

	def _make_journal_entry(self):
		if not (self.bank_cash_account and self.contra_account):
			frappe.throw(frappe._("Set both Bank/Cash Account and Contra Account"))
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = self.company
		je.posting_date = self.posting_date
		je.user_remark = self.text or self.name
		je.append("accounts", {"account": self.contra_account, "debit_in_account_currency": self.amount})
		je.append("accounts", {"account": self.bank_cash_account, "credit_in_account_currency": self.amount})
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		self.db_set("internal_voucher_type", "Journal Entry")
		self.db_set("internal_voucher", je.name)

	def _cancel_internal(self):
		if self.internal_voucher and self.internal_voucher_type:
			if frappe.db.exists(self.internal_voucher_type, self.internal_voucher):
				doc = frappe.get_doc(self.internal_voucher_type, self.internal_voucher)
				if doc.docstatus == 1:
					doc.flags.ignore_permissions = True
					doc.cancel()
