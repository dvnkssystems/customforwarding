# Copyright (c) 2026, DVNKS Systems and contributors
"""Daily shipment reminders, delivered to each user's notification bell.

Two warnings for open jobs:

  * free time ends within FREE_TIME_WARNING_DAYS — return containers or pay
    demurrage / detention;
  * the shipment arrives within ARRIVAL_WARNING_DAYS.

A reminder is looked for across the whole window rather than on one exact day,
so a day the scheduler did not run is not a reminder lost. Each is sent once:
the subject carries the date, and a job that already has that notification is
skipped. Change the ETA or free time and the new date gets its own reminder.
"""

import json

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.utils import add_days, formatdate, getdate, nowdate

FREE_TIME_WARNING_DAYS = 2
ARRIVAL_WARNING_DAYS = 5

OPEN_JOBS = {
	"docstatus": ["<", 2],
	"operations_status": ["!=", "Closed"],
	"is_trashed": 0,
}


def send_shipment_reminders():
	today = getdate(nowdate())

	remind(
		date_field="free_time_expiry",
		window=(today, add_days(today, FREE_TIME_WARNING_DAYS)),
		subject=lambda job: _("Free time for {0} ends on {1}. Return the containers to avoid penalty charges.").format(
			job.name, formatdate(job.free_time_expiry)
		),
	)
	remind(
		date_field="eta_date",
		window=(today, add_days(today, ARRIVAL_WARNING_DAYS)),
		subject=lambda job: _("{0} for {1} arrives on {2}.").format(
			job.name, job.customer or _("the customer"), formatdate(job.eta_date)
		),
	)


def remind(date_field, window, subject):
	jobs = frappe.get_all(
		"Operations",
		filters={**OPEN_JOBS, date_field: ["between", list(window)]},
		fields=["name", "owner", "_assign", "customer", date_field],
	)
	for job in jobs:
		text = subject(job)
		if frappe.db.exists(
			"Notification Log", {"document_type": "Operations", "document_name": job.name, "subject": text}
		):
			continue

		users = recipients(job)
		if not users:
			continue

		enqueue_create_notification(
			users,
			{
				"type": "Alert",
				"document_type": "Operations",
				"document_name": job.name,
				"subject": text,
				"from_user": "Administrator",
			},
		)


def recipients(job):
	"""Email addresses of the job's creator and assignees who can still log in.

	Emails, not user IDs: the notification helper looks users up by email, and
	an ID is not always one — `Administrator`'s is not, so passing IDs silently
	dropped every reminder meant for it.
	"""
	users = {job.owner}
	try:
		users.update(json.loads(job._assign or "[]"))
	except ValueError:
		pass

	users.discard("Guest")
	emails = []
	for user in users:
		enabled, email = frappe.db.get_value("User", user, ["enabled", "email"]) or (0, None)
		if enabled and email:
			emails.append(email)
	return emails
