# Copyright (c) 2026, DVNKS Systems and contributors
"""QA Round 2: no "None" in printed addresses (R2-04) and the customer-facing
"Freight Tax Invoice" print format (R2-06). Everything is rolled back."""

import re
import sys
from unittest.mock import patch

import frappe
from frappe.contacts.doctype.address.address import get_address_display
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from forwarding import invoice_print
from forwarding.patches.v1_0 import default_sales_invoice_print_format, fix_address_template_none
from forwarding.tests.test_job_360 import CUSTOMER, ITEM, make

PRINT_FORMAT = "Freight Tax Invoice"
SELLER_VAT = "300000000000003"
BUYER_VAT = "311111111100003"
INTERNAL_LABELS = (
	"Cost Center",
	"b_abb",
	"Update Billed Amount",
	"ZATCA Discount Reason",
	"Cost Table",
	"Amount Eligible for Commission",
)


def tax_account(company):
	name = frappe.db.get_value("Account", {"company": company, "account_type": "Tax", "is_group": 0}, "name")
	if not name:
		raise frappe.DoesNotExistError("Test needs a Tax account")
	return name


def make_address(**values):
	return frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": "R2 Print Test",
			"address_line1": "Ring Road 5",
			"city": "Surat",
			"country": "Saudi Arabia",
			"links": [{"link_doctype": "Customer", "link_name": CUSTOMER}],
			**values,
		}
	).insert(ignore_permissions=True)


def make_invoice(job=None, submit=False, **values):
	company = job.company if job else frappe.db.get_value("Company", {}, "name")
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": company,
			"customer": CUSTOMER,
			"operations": job.name if job else None,
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"set_posting_time": 1,
			"items": [
				{"item_code": ITEM, "qty": 2, "rate": 1000},
				{"item_code": ITEM, "qty": 1, "rate": 200},
			],
			"taxes": [
				{
					"charge_type": "On Net Total",
					"account_head": tax_account(company),
					"rate": 15,
					"description": "VAT 15%",
				}
			],
			**values,
		}
	).insert(ignore_permissions=True)
	if submit:
		si.submit()
	return si


def visible_text(html):
	return re.sub(r"<[^>]+>", " ", html)


class InvoicePrintCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		fix_address_template_none.fix_templates()
		default_sales_invoice_print_format.execute()
		self.company = frappe.db.get_value("Company", {}, "name")
		frappe.db.set_value("Company", self.company, "tax_id", SELLER_VAT)
		frappe.db.set_value("Customer", CUSTOMER, "tax_id", BUYER_VAT)


class TestAddressNone(InvoicePrintCase):
	def test_address_lines_drop_none(self):
		self.assertEqual(
			invoice_print.address_lines("Ring Road 5<br>Surat, None<br> \nNone\nSaudi Arabia<br>\n"),
			["Ring Road 5", "Surat", "Saudi Arabia"],
		)
		self.assertEqual(invoice_print.address_lines(None), [])

	def test_bare_template_field_is_guarded(self):
		fixed = fix_address_template_none.guard_bare_fields("{{ city }}<br>\n{{ custom_area }}\n{{ country }}<br>")
		self.assertIn("{% if custom_area %}{{ custom_area }}<br>{% endif -%}", fixed)
		self.assertIn("{{ city }}<br>", fixed)
		# Idempotent.
		self.assertEqual(fix_address_template_none.guard_bare_fields(fixed), fixed)

	def test_empty_area_and_state_render_without_none(self):
		frappe.db.set_value(
			"Address Template", "Saudi Arabia", "template", "{{ address_line1 }}<br>{{ city }}<br>\n{{ custom_area }}\n{{ country }}<br>"
		)
		fix_address_template_none.fix_templates()
		address = make_address()
		display = get_address_display(address.name)
		self.assertNotIn("None", display)
		self.assertIn("Surat", display)

	def test_drafts_rerendered_submitted_kept(self):
		address = make_address()
		draft = make_invoice(customer_address=address.name)
		submitted = make_invoice(customer_address=address.name, submit=True)
		broken = "Ring Road 5<br>Surat<br> \nNone\nSaudi Arabia<br>\n"
		for si in (draft, submitted):
			frappe.db.set_value("Sales Invoice", si.name, "address_display", broken, update_modified=False)

		fix_address_template_none.rerender_draft_invoices()

		self.assertNotIn("None", frappe.db.get_value("Sales Invoice", draft.name, "address_display"))
		self.assertEqual(frappe.db.get_value("Sales Invoice", submitted.name, "address_display"), broken)
		# ...and the submitted one still prints without "None".
		html = frappe.get_print("Sales Invoice", submitted.name, print_format=PRINT_FORMAT)
		self.assertNotIn("None", visible_text(html))
		self.assertIn("Surat", html)


class TestTaxInvoiceFormat(InvoicePrintCase):
	def test_default_print_format(self):
		self.assertEqual(frappe.get_meta("Sales Invoice").default_print_format, PRINT_FORMAT)
		default_sales_invoice_print_format.execute()  # idempotent
		self.assertEqual(
			frappe.db.count("Property Setter", {"doc_type": "Sales Invoice", "property": "default_print_format"}),
			1,
		)
		self.assertEqual(frappe.db.get_value("Print Format", PRINT_FORMAT, "module"), "Forwarding")

	def test_context(self):
		job = make(awb_number="MSKU7654321", house_number="HBL-R2")
		si = make_invoice(job)
		c = invoice_print.get_tax_invoice_context(si)
		self.assertEqual(c.seller.tax_id, SELLER_VAT)
		self.assertEqual(c.buyer.tax_id, BUYER_VAT)
		self.assertEqual(c.job_no, job.name)
		self.assertEqual(c.bl_awb, "MSKU7654321")
		self.assertTrue(c.has_line_vat)
		self.assertEqual([line.vat_amount for line in c.lines], [300.0, 30.0])
		self.assertEqual(c.total_vat, 330)
		self.assertEqual(c.grand_total, 2530)
		self.assertTrue(c.words_ar)
		if si.currency == "SAR":
			self.assertIn("ريال سعودي", c.words_ar)

	def test_line_vat_from_item_tax_rate_without_detail_table(self):
		si = make_invoice()
		si.item_wise_tax_details = []
		si.items[1].item_tax_rate = frappe.as_json({si.taxes[0].account_head: 0})
		vat = invoice_print._line_vat(si)
		self.assertEqual(vat[si.items[0].name], (15, 300))
		self.assertEqual(vat[si.items[1].name], (0, 0))

	def test_arabic_words_fallback_without_num2words(self):
		with patch.dict(sys.modules, {"num2words": None}):
			self.assertEqual(invoice_print.amount_in_words_ar(10, "SAR"), "")
		self.assertTrue(invoice_print.amount_in_words_ar(1250.75, "SAR").endswith("فقط لا غير"))

	def test_rendered_html(self):
		job = make(awb_number="MSKU7654321")
		si = make_invoice(job, submit=True)
		# No format named: the default is used, as by /printview and download_pdf.
		html = frappe.get_print("Sales Invoice", si.name)
		self.assertIn('class="fti"', html)
		for value in (SELLER_VAT, BUYER_VAT, job.name, "MSKU7654321", si.name, "فاتورة ضريبية"):
			self.assertIn(value, html)
		text = visible_text(html)
		for label in INTERNAL_LABELS:
			self.assertNotIn(label, text)
		self.assertNotIn("<img", html)

	def test_qr_only_when_file_exists(self):
		si = make_invoice()
		si.db_set("ksa_einv_qr", "/files/does-not-exist-r2.png", update_modified=False)
		html = frappe.get_print("Sales Invoice", si.name, print_format=PRINT_FORMAT)
		self.assertNotIn("<img", html)

		with patch("forwarding.invoice_print._existing_file", side_effect=lambda url: url):
			html = frappe.get_print("Sales Invoice", si.name, print_format=PRINT_FORMAT)
		self.assertIn('src="/files/does-not-exist-r2.png"', html)

	def test_pdf_endpoint(self):
		from forwarding.print_pdf import download_pdf

		si = make_invoice()
		download_pdf("Sales Invoice", si.name)
		self.assertEqual(frappe.local.response.type, "pdf")
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))
