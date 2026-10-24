# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""A licence, certificate or contract kept on a Customer or Supplier (Phase 2
spec §5.3). The rows are checked and their expiry status set by the parent's
validate hook, forwarding.party_documents.validate."""

from frappe.model.document import Document


class PartyDocument(Document):
	pass
