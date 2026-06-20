# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Auto-generate CU-/SU- party codes (separate from the primary name series)."""

from frappe.model.naming import make_autoname


def set_customer_code(doc, method=None):
	if not doc.get("customer_code"):
		doc.customer_code = make_autoname("CU-.YY.MM.-.####")


def set_supplier_code(doc, method=None):
	if not doc.get("supplier_code"):
		doc.supplier_code = make_autoname("SU-.YY.MM.-.####")
