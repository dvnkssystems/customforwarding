# Copyright (c) 2026, DVNKS Systems and contributors
"""Go-live clean-up for ONE FREIGHT SERVICES COMPANY (Simran, 3 Nov): clear
every test record, remove the sample truck and driver, and start job,
invoice, transport and customer numbering again at 0001.

Run by hand on go-live day, never from a migrate (it is not a patch):

    # Trial run: lists what would go, changes nothing.
    bench --site <site> execute forwarding.golive.clean_test_data

    # The real thing, after a backup.
    bench --site <site> execute forwarding.golive.clean_test_data \
        --kwargs '{"confirm": "ONE FREIGHT SERVICES COMPANY"}'

Everything listed in TEST_DATA goes: until go-live nothing on the site is
real data. Masters stay (suppliers, ports, items, accounts, settings,
users). A record something else still needs is kept and reported, not
forced.
"""

import re

import frappe

from forwarding.patches.v1_0.ofs1_clean_start import remove
from forwarding.patches.v1_0.ofs1_retest2 import SAMPLE_DRIVER, SAMPLE_PLATE
from forwarding.patches.v1_0.ofs1_retest3 import reset_job_counter

COMPANY = "ONE FREIGHT SERVICES COMPANY"

# In order: what points at a record goes before it.
TEST_DATA = [
	"Payment Entry",
	"Journal Entry",
	"Sales Invoice",
	"Purchase Invoice",
	"POS Invoice",
	"Delivery Note",
	"Sales Order",
	"Purchase Order",
	"Freight Voucher",
	"Freight Waybill",
	"Freight Tracking",
	"Freight Job Status",
	"Freight Job Stage Assignment",
	"Freight Job Request",
	"Terminal Management",
	"Custom Clearance",
	"Freight",
	"Transportation",
	"Quote",
	"Quotation",
	"Operations",
	"Timesheet",
	"Project",
	"Opportunity",
	"Prospect",
	"Lead",
	"Issue",
	"Call Log",
	"Customer",
]
TAIL_NUMBER = re.compile(r"^(.*?)(\d+)$")


def clean_test_data(confirm=None):
	"""Trial run unless `confirm` is the company's name."""
	try:
		_clean(dry_run=confirm != COMPANY)
	except Exception:
		import traceback

		print(traceback.format_exc())
		frappe.db.rollback()


def _clean(dry_run):
	if not frappe.db.exists("Company", COMPANY):
		print(f"Not run: this site has no {COMPANY}.")
		return
	print("TRIAL RUN: nothing is changed." if dry_run else "Clearing test data.")

	plan = [(dt, names) for dt in TEST_DATA if frappe.db.table_exists(dt) for names in [all_names(dt)] if names]
	addresses = party_records("Address")
	contacts = party_records("Contact")
	fleet = [("Vehicle", n) for n in [SAMPLE_PLATE] if frappe.db.exists("Vehicle", n)] + [
		("Driver", n) for n in frappe.get_all("Driver", filters={"full_name": SAMPLE_DRIVER}, pluck="name")
	]

	for doctype, names in plan:
		print(f"  {doctype}: {len(names)} ({', '.join(names[:8])}{' …' if len(names) > 8 else ''})")
	print(f"  Customer addresses: {len(addresses)}, contacts: {len(contacts)}")
	print(f"  Sample fleet: {', '.join(f'{dt} {n}' for dt, n in fleet) or 'none'}")
	series = series_of(plan)
	print(f"  Numbering back to 0001: {', '.join(sorted(series)) or 'nothing to reset'}; job counter too")
	if dry_run:
		return

	for doctype, names in plan:
		for name in names:
			remove(doctype, name)
	for doctype, names in (("Address", addresses), ("Contact", contacts)):
		for name in names:
			remove(doctype, name)
	for doctype, name in fleet:
		remove(doctype, name)

	for prefix in sorted(series):
		still = highest_in_use(prefix, [dt for dt, _ in plan])
		frappe.db.sql("update `tabSeries` set current = %s where name = %s", (still, prefix))
		print(f"Series {prefix}: next is {still + 1:04d}")
	reset_job_counter()
	frappe.db.commit()

	left = {dt: frappe.db.count(dt) for dt, _ in plan if frappe.db.count(dt)}
	print("Done." if not left else f"Done; kept (still needed elsewhere): {left}")


def all_names(doctype):
	# Newest first: a later record (a credit note, an amendment) points at an earlier one.
	return frappe.get_all(doctype, pluck="name", order_by="creation desc")


def party_records(doctype):
	"""Addresses / contacts that belong only to customers (never the company's)."""
	linked = frappe.get_all(
		"Dynamic Link", filters={"parenttype": doctype, "link_doctype": "Customer"}, pluck="parent", distinct=True
	)
	other = set(
		frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": doctype, "parent": ["in", linked or [""]], "link_doctype": ["!=", "Customer"]},
			pluck="parent",
		)
	)
	return [name for name in linked if name not in other]


def series_of(plan):
	"""The numbering series the records were named from (their name, and a
	customer's code), e.g. "JSI-26-" from JSI-26-0001."""
	prefixes = set()
	for doctype, names in plan:
		for name in names:
			values = [name]
			if doctype == "Customer":
				values.append(frappe.db.get_value("Customer", name, "customer_code"))
			for value in filter(None, values):
				match = TAIL_NUMBER.match(str(value))
				if match and frappe.db.sql("select 1 from `tabSeries` where name = %s", match.group(1)):
					prefixes.add(match.group(1))
	return prefixes


def highest_in_use(prefix, doctypes):
	"""The highest number a remaining record carries in that series (0 if none)."""
	highest = 0
	for doctype in doctypes:
		for name in frappe.get_all(doctype, filters={"name": ["like", f"{prefix}%"]}, pluck="name"):
			match = TAIL_NUMBER.match(name)
			if match and match.group(1) == prefix:
				highest = max(highest, int(match.group(2)))
	return highest
