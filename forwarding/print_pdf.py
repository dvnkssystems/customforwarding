# Copyright (c) 2026, DVNKS Systems and contributors
"""Get PDF from the print view.

/printview builds its "Get PDF" link with `pdf_generator={{ pdf_generator }}`,
taken from the Print Format. A format that never set PDF Generator (most of
them, and every format made before the field existed) renders that as the
text "None", which download_pdf's type check refuses with a 417. Treat an
empty or unknown generator as "use the default" and hand over to Frappe.
"""

import frappe
from frappe.utils.print_format import download_pdf as frappe_download_pdf

GENERATORS = ("wkhtmltopdf", "chrome")


@frappe.whitelist(allow_guest=True)
def download_pdf(
	doctype: str,
	name: str,
	format=None,
	doc=None,
	no_letterhead=0,
	language=None,
	letterhead=None,
	pdf_generator: str | None = None,
):
	if pdf_generator not in GENERATORS:
		pdf_generator = None
	if letterhead in ("None", ""):
		letterhead = None
	return frappe_download_pdf(
		doctype,
		name,
		format=format,
		doc=doc,
		no_letterhead=no_letterhead,
		language=language,
		letterhead=letterhead,
		pdf_generator=pdf_generator,
	)
