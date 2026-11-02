# Copyright (c) 2026, DVNKS Systems and contributors
"""Transport Charges item group (B3-11, Simran 2 Nov).

A Transportation made from a job copied the job's whole estimate into its
Costs, so a Documentation Fee counted on the job and again on the transport.
Its Costs now take only the items of the "Transport Charges" group
(operations.TRANSPORT_ITEM_GROUP); this creates the group and moves the
land-transport charges into it.

TRANSPORT_ITEMS is the one list to extend: 4009-R-TRAN & CLR and
4012-R-LABOUR HANDLING CHARGES await Simran's confirmation. Items missing on
a site are skipped; running it again changes nothing.
"""

import frappe

from forwarding.forwarding.doctype.operations.operations import TRANSPORT_ITEM_GROUP

TRANSPORT_ITEMS = (
	"4004-R-TRANS",
	"4006-NR-LAND FREIGHT",
	"4033-R-EXPORT TRANSPORTATION",
	"TRUCK WAITING CHARGE",
)


def execute():
	if not frappe.db.exists("Item Group", TRANSPORT_ITEM_GROUP):
		parent = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]}, "name")
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": TRANSPORT_ITEM_GROUP,
				"parent_item_group": parent or "All Item Groups",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)

	for item in TRANSPORT_ITEMS:
		if frappe.db.exists("Item", item):
			frappe.db.set_value("Item", item, "item_group", TRANSPORT_ITEM_GROUP, update_modified=False)
