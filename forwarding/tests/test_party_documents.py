# Copyright (c) 2026, DVNKS Systems and contributors
"""Party Documents (Phase 2 spec §5.3, CU3, SU9, banners C4 / C6 / S7 / S8).

Expiry status boundaries, the expiry-before-issue rule, the Customer 360 and
Supplier 360 payload (list order, KPIs, Documents on file, no date range) and
the four banners. Everything is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from forwarding import party_documents
from forwarding.party_documents import EXPIRED, EXPIRING, NO_EXPIRY, VALID
from forwarding.tests.test_customer_360 import fresh as fresh_customer
from forwarding.tests.test_customer_360 import is_cached as customer_is_cached
from forwarding.tests.test_customer_360 import make_customer as _make_customer
from forwarding.tests.test_supplier_360 import codes, fresh, make_supplier

PAYLOAD_KEYS = {
	"name",
	"document_type",
	"document_no",
	"issue_date",
	"expiry_date",
	"attach",
	"expiry_status",
	"days_left",
}


def make_customer(**values):
	# CR No. and a VAT number are mandatory on this site's Customer.
	return _make_customer(
		**{"cr_no": "1010999999", "custom_vat_registration_number": "300000000000003", **values}
	)


def in_days(n):
	return add_days(nowdate(), n)


def banner(payload, code):
	return next((b for b in payload["banners"] if b["code"] == code), None)


class TestPartyDocuments(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		patcher = patch("frappe.model.document.run_server_script_for_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)

	# -- Expiry status ---------------------------------------------------------------

	def test_expiry_status_boundaries(self):
		today = getdate(nowdate())
		status = party_documents.expiry_status
		self.assertEqual(status(today, today, 30), EXPIRING)
		self.assertEqual(status(add_days(today, 30), today, 30), EXPIRING)
		self.assertEqual(status(add_days(today, 31), today, 30), VALID)
		self.assertEqual(status(add_days(today, -1), today, 30), EXPIRED)
		self.assertEqual(status(None, today, 30), NO_EXPIRY)

	def test_warning_days_come_from_settings(self):
		with patch.object(party_documents, "expiry_days", return_value=10):
			self.assertEqual(party_documents.expiry_status(in_days(11)), VALID)
			self.assertEqual(party_documents.expiry_status(in_days(10)), EXPIRING)

	def test_expiry_before_issue_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_customer(
				party_documents=[{"document_type": "CR", "issue_date": in_days(0), "expiry_date": in_days(-1)}]
			)
		with self.assertRaises(frappe.ValidationError):
			make_supplier(
				party_documents=[{"document_type": "Insurance", "issue_date": in_days(5), "expiry_date": in_days(4)}]
			)
		# Same day is fine.
		make_customer(party_documents=[{"document_type": "CR", "issue_date": in_days(0), "expiry_date": in_days(0)}])

	def test_save_sets_the_stored_status(self):
		c = make_customer(
			party_documents=[
				{"document_type": "CR", "expiry_date": in_days(40)},
				{"document_type": "Other"},
			]
		)
		self.assertEqual([r.expiry_status for r in c.party_documents], [VALID, NO_EXPIRY])

	def test_fields_on_customer_and_supplier(self):
		for dt in ("Customer", "Supplier"):
			field = frappe.get_meta(dt).get_field("party_documents")
			self.assertEqual((field.fieldtype, field.options), ("Table", "Party Document"), dt)
		meta = frappe.get_meta("Party Document")
		self.assertTrue(meta.istable)
		self.assertEqual(meta.get_field("attach").fieldtype, "Attach")
		self.assertTrue(meta.get_field("expiry_status").read_only)

	# -- Customer 360 ----------------------------------------------------------------

	def test_customer_payload_order_and_kpis(self):
		c = make_customer(
			party_documents=[
				{"document_type": "Contract", "document_no": "K-1"},
				{"document_type": "VAT Certificate", "expiry_date": in_days(200), "attach": "/files/vat.pdf"},
				{"document_type": "Insurance", "expiry_date": in_days(10)},
				{"document_type": "CR", "document_no": "1010", "expiry_date": in_days(-3)},
				{"document_type": "Trade Licence", "expiry_date": in_days(2), "document_no": "TL"},
				{"document_type": "Other", "expiry_date": in_days(-30)},
			]
		)
		# Stored statuses are not trusted: a stale one is worked out again.
		frappe.db.set_value("Party Document", c.party_documents[0].name, "expiry_status", EXPIRED)

		payload = fresh_customer(c.name)
		rows = payload["party_documents"]
		self.assertEqual(set(rows[0]), PAYLOAD_KEYS)
		self.assertEqual(
			[(r["document_type"], r["expiry_status"]) for r in rows],
			[
				("Other", EXPIRED),
				("CR", EXPIRED),
				("Trade Licence", EXPIRING),
				("Insurance", EXPIRING),
				("VAT Certificate", VALID),
				("Contract", NO_EXPIRY),
			],
		)
		self.assertEqual([r["days_left"] for r in rows], [-30, -3, 2, 10, 200, None])
		self.assertEqual(rows[1]["expiry_date"], str(getdate(in_days(-3))))

		kpis = payload["kpis"]
		self.assertEqual(
			(kpis["party_documents_count"], kpis["party_documents_expiring"], kpis["party_documents_expired"]),
			(6, 2, 2),
		)
		# On file: a file or a number (Contract, VAT, CR, Trade Licence).
		self.assertEqual((kpis["documents_on_file"], kpis["documents_total"]), (4, 6))

	def test_party_document_file_counts_once(self):
		c = make_customer(party_documents=[{"document_type": "CR", "attach": "/files/pd-cr.pdf"}])
		# The desk attaches a child row's file to the parent as well.
		for url in ("/files/pd-cr.pdf", "/files/pd-other.pdf"):
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": url.rsplit("/", 1)[1],
					"file_url": url,
					"attached_to_doctype": "Customer",
					"attached_to_name": c.name,
					"is_private": 0,
				}
			).db_insert()

		payload = fresh_customer(c.name)
		self.assertEqual([d["attach"] for d in payload["documents"]], ["/files/pd-other.pdf"])
		self.assertEqual((payload["kpis"]["documents_on_file"], payload["kpis"]["documents_total"]), (2, 2))

	def test_customer_list_ignores_the_date_range(self):
		c = make_customer(party_documents=[{"document_type": "CR", "expiry_date": in_days(-400)}])
		from forwarding.api import customer_360

		payload = customer_360.get(c.name, from_date=in_days(-5), to_date=in_days(0))
		self.assertEqual(len(payload["party_documents"]), 1)
		self.assertEqual(payload["kpis"]["party_documents_expired"], 1)

	def test_customer_save_clears_the_cache(self):
		c = make_customer()
		self.assertEqual(fresh_customer(c.name)["party_documents"], [])
		self.assertTrue(customer_is_cached(c.name))
		c.append("party_documents", {"document_type": "CR", "expiry_date": in_days(5)})
		c.save(ignore_permissions=True)
		self.assertFalse(customer_is_cached(c.name))

	def test_customer_banners(self):
		c = make_customer(party_documents=[{"document_type": "CR", "expiry_date": in_days(20)}])
		payload = fresh_customer(c.name)
		c4 = banner(payload, "C4")
		self.assertEqual((c4["colour"], c4["action"]), ("warning", "view_documents"))
		self.assertEqual(c4["message"], f"CR expires {_date(in_days(20))}")
		self.assertIsNone(banner(payload, "C6"))

		c.party_documents[0].expiry_date = in_days(-2)
		c.append("party_documents", {"document_type": "VAT Certificate", "expiry_date": in_days(-9)})
		c.save(ignore_permissions=True)
		payload = fresh_customer(c.name)
		c6 = banner(payload, "C6")
		self.assertEqual((c6["colour"], c6["action"]), ("critical", "view_documents"))
		self.assertEqual(c6["message"], "2 documents have expired")
		# A row is expired or expiring, never both.
		self.assertIsNone(banner(payload, "C4"))

	# -- Supplier 360 ----------------------------------------------------------------

	def test_supplier_payload_and_banners(self):
		s = make_supplier(
			party_documents=[
				{"document_type": "Trade Licence", "document_no": "TL-1", "expiry_date": in_days(-5)},
				{"document_type": "Insurance", "expiry_date": in_days(365), "attach": "/files/ins.pdf"},
			]
		)
		payload = fresh(s.name)
		self.assertEqual(
			[(r["document_type"], r["expiry_status"], r["days_left"]) for r in payload["party_documents"]],
			[("Trade Licence", EXPIRED, -5), ("Insurance", VALID, 365)],
		)
		kpis = payload["kpis"]
		self.assertEqual(
			(kpis["party_documents_count"], kpis["party_documents_expiring"], kpis["party_documents_expired"]),
			(2, 0, 1),
		)
		self.assertEqual((kpis["documents_on_file"], kpis["documents_total"]), (2, 2))

		s8 = banner(payload, "S8")
		self.assertEqual((s8["colour"], s8["action"]), ("critical", "view_documents"))
		self.assertEqual(s8["message"], f"Trade Licence expired {_date(in_days(-5))}")
		self.assertNotIn("S7", codes(payload))

		s.append("party_documents", {"document_type": "Customs Broker Licence", "expiry_date": in_days(1)})
		s.append("party_documents", {"document_type": "Contract", "expiry_date": in_days(30)})
		s.save(ignore_permissions=True)
		s7 = banner(fresh(s.name), "S7")
		self.assertEqual((s7["colour"], s7["action"]), ("warning", "view_documents"))
		self.assertEqual(s7["message"], "2 documents expire within 30 days")

	def test_no_documents_no_banners(self):
		payload = fresh(make_supplier().name)
		self.assertEqual(payload["party_documents"], [])
		self.assertFalse({"S7", "S8"} & set(codes(payload)))
		self.assertEqual(payload["kpis"]["party_documents_count"], 0)


def _date(value):
	from forwarding.banners import format_date

	return format_date(value)
