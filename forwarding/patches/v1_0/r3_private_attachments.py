# Copyright (c) 2026, DVNKS Systems and contributors
"""Round 3 (R3-10): move the public files attached to freight records to
private/files.

Uses forwarding.private_files.make_private for each one, so Frappe's File
moves the file on disk and the URLs stored in the record's Attach fields
(child-table rows included) become /private/files/... A file also used by a
record outside the app (shared upload, same content) is left public and
counted, as is one whose file is missing on disk or clashes with a private
file of the same name. Running it again changes nothing.
"""

import frappe

from forwarding.private_files import make_private, private_doctypes


def execute():
	doctypes = sorted(private_doctypes())
	if not doctypes:
		return
	candidates = frappe.get_all(
		"File",
		filters=[
			["attached_to_doctype", "in", doctypes],
			["is_private", "=", 0],
			["is_folder", "=", 0],
			["file_url", "like", "/files/%"],
		],
		pluck="name",
	)
	moved = left_shared = failed = 0
	for name in candidates:
		if not frappe.db.exists("File", name) or frappe.db.get_value("File", name, "is_private"):
			continue  # moved already, as a sibling of an earlier one
		try:
			if make_private(name) is not None:
				moved += 1
			else:
				left_shared += 1
		except (FileNotFoundError, FileExistsError) as e:
			failed += 1
			frappe.clear_last_message()
			print(f"R3-10: left File {name} public: {e}")
	print(
		f"R3-10: {len(candidates)} public attachments on freight records; moved {moved} to private, "
		f"left {left_shared} shared with other records, {failed} could not be moved"
	)
