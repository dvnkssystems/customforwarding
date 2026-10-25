# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-54): one Deadline per cut-off instead of Earliest / Latest.

Each Job Cutoff row's Deadline is its Latest time, or its Earliest when it
had no Latest (a cut-off is the last moment, so Latest is the one that
counts). Earliest and Latest stay, hidden. Every row's status is worked out
again with the new values: Upcoming / Due today / Missed, or Done once the
job's ATD is recorded. Running it again changes nothing.
"""

import frappe

from forwarding.forwarding.doctype.operations.operations import get_cutoff_status


def execute():
	rows = frappe.db.sql(
		"""select c.name, c.deadline, c.latest, c.earliest, o.atd_date
		from `tabJob Cutoff` c left join `tabOperations` o on o.name = c.parent
		where c.parenttype = %s""",
		("Operations",),
		as_dict=True,
	)
	moved = 0
	for row in rows:
		deadline = row.deadline or row.latest or row.earliest
		if deadline and not row.deadline:
			moved += 1
		frappe.db.set_value(
			"Job Cutoff",
			row.name,
			{"deadline": deadline, "cutoff_status": get_cutoff_status(deadline, done=bool(row.atd_date))},
			update_modified=False,
		)
	print(f"R3-54: {len(rows)} cut-off rows, {moved} given a Deadline from Latest / Earliest")
