# Copyright (c) 2026, DVNKS Systems and contributors
"""Job Type list (M-14): withdrawn.

This patch once renamed LAND TRANSPORT to Domestic (abbreviation DM) and
deleted Others. Simran asked to keep both as they were (Slack, 24 Oct), so it
now does nothing. It stays in patches.txt because it already ran on
production; r2_job_types_revert puts LAND TRANSPORT and Others back where it
did.
"""


def execute():
	return
