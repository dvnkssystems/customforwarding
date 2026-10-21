# Copyright (c) 2026, DVNKS Systems and contributors
"""A zero-value invoice no longer counts as Paid (get_billing_status).
Re-derive billing_status on every job that has a submitted invoice, without
saving the job. Idempotent."""

import frappe

from forwarding.job_events import update_billing_status


def execute():
	jobs = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "operations": ["is", "set"]},
		pluck="operations",
		distinct=True,
	)
	update_billing_status(*jobs)
