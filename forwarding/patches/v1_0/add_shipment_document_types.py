# Copyright (c) 2026, DVNKS Systems and contributors
"""Add the shipment documents the job checklist is meant to cover.

The Document List master held only FINAL BL/AWB and COMMERCIAL INVOICE, but the
paperwork a Sea or Air job is actually chased for also includes the Saber
certificate and the D/O authorisation. Until they exist as records they cannot
be picked on a job at all, so the checklist had no way to record them.

Only what is missing is added, so a name someone has already created by hand --
or spelled differently -- is left alone. Which documents a given Shipment Type
expects is left for the users to set on the Shipment Type itself: seeding every
Sea and Air type here would start warning on well over a thousand existing jobs
that were filed before the checklist existed.
"""

import frappe

DOCUMENTS = (
	"SABER",
	"D/O AUTHORISATION",
)


def execute():
	for document_name in DOCUMENTS:
		if frappe.db.exists("Document List", document_name):
			continue

		frappe.get_doc(
			{"doctype": "Document List", "document_name": document_name}
		).insert(ignore_permissions=True)
