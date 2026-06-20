# Copyright (c) 2026, DVNKS Systems and contributors
"""Public 'Received Jobs' intake form — /freight-job-request (guest)."""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.job_types = ["Import", "Export", "Local"]
	return context
