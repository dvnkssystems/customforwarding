# Copyright (c) 2026, DVNKS Systems and contributors
"""Finishes ofs1_clean_start on ONE FREIGHT SERVICES COMPANY. Simran's test job
J-IM-S-26-00001 had a Project of the same name, made with the job, which kept
customer "TEST CUSTOMER (delete)" from being deleted. The Project goes (only
once its job is gone), then the customer.
"""

import frappe

from forwarding.patches.v1_0.ofs1_clean_start import COMPANY, remove

JOB = "J-IM-S-26-00001"
CUSTOMER = "TEST CUSTOMER (delete)"


def execute():
	if not frappe.db.exists("Company", COMPANY) or frappe.db.exists("Operations", JOB):
		return
	remove("Project", JOB)
	remove("Customer", CUSTOMER)
