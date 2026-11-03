# Copyright (c) 2026, DVNKS Systems and contributors
"""Transportation's new Driver Name (ONE Freight, 3 Nov: the form showed the
driver as HR-DRI-2026-00001) filled on the transports that already have a
driver. New ones fetch it from the driver when saved. Every site."""

import frappe


def execute():
	if not frappe.db.has_column("Transportation", "driver_name"):
		return
	frappe.db.sql(
		"""update `tabTransportation` t join `tabDriver` d on d.name = t.driver
		set t.driver_name = d.full_name
		where ifnull(t.driver_name, '') = ''"""
	)
