# Copyright (c) 2026, DVNKS Systems and contributors
"""Files attached to freight records are private (R3-10).

Shipping documents, customs papers and party KYC carry commercial data, so a
file attached to one of the app's records is saved under /private/files,
served only to signed-in users allowed to read the record.

* `upload_file` (hooked over Frappe's, see hooks.override_whitelisted_methods)
  marks an upload for one of these records private before Frappe saves it, so
  the file lands in private/files from the start and is not de-duplicated
  against a public copy.
* `on_file_insert` (File after_insert) catches a public file attached to one
  of these records some other way and moves it.
* `make_private` moves one File: Frappe's File moves it on disk and rewrites
  the URL of the File records sharing it, and this rewrites the URL stored in
  the record's Attach fields, child-table rows included (Frappe only updates
  a top-level field).
"""

import frappe
from frappe.utils import cint

# Records outside the Forwarding module whose attachments are the app's:
# Quote is a custom DocType, Customer / Supplier hold Party Documents.
EXTRA_DOCTYPES = ("Quote", "Customer", "Supplier")
ATTACH_TYPES = ("Attach", "Attach Image")


def private_doctypes():
	"""Every non-child DocType of the Forwarding module, plus EXTRA_DOCTYPES."""
	cached = getattr(frappe.local, "forwarding_private_doctypes", None)
	if cached is None:
		cached = set(frappe.get_all("DocType", filters={"module": "Forwarding", "istable": 0}, pluck="name"))
		cached.update(dt for dt in EXTRA_DOCTYPES if frappe.db.exists("DocType", dt))
		frappe.local.forwarding_private_doctypes = cached
	return cached


def is_private_doctype(doctype):
	return bool(doctype) and doctype in private_doctypes()


@frappe.whitelist(allow_guest=True, methods=["POST"])
def upload_file():
	"""Frappe's upload_file, with the file private when it is attached to a
	freight record."""
	from frappe.handler import upload_file as frappe_upload_file

	if is_private_doctype(frappe.form_dict.doctype) and not frappe.form_dict.get("library_file_name"):
		frappe.form_dict.is_private = 1
	return frappe_upload_file()


def _shared_elsewhere(file_doc):
	"""True when another File record uses the same file and is not attached to
	a freight record: moving the file would make theirs private too."""
	filters = [["name", "!=", file_doc.name]]
	others = frappe.get_all(
		"File",
		filters=filters + [["file_url", "=", file_doc.file_url]],
		fields=["attached_to_doctype"],
	)
	if file_doc.content_hash:
		others += frappe.get_all(
			"File",
			filters=filters + [["content_hash", "=", file_doc.content_hash], ["is_private", "=", 0]],
			fields=["attached_to_doctype"],
		)
	return any(not is_private_doctype(o.attached_to_doctype) for o in others)


def replace_attach_urls(doctype, name, old_url, new_url):
	"""Point every Attach / Attach Image value of the record (and its child
	rows) that holds old_url at new_url. Returns how many fields changed."""
	if not (doctype and name and old_url and new_url) or old_url == new_url:
		return 0
	meta = frappe.get_meta(doctype)
	changed = 0
	for df in meta.fields:
		if df.fieldtype in ATTACH_TYPES and not meta.issingle:
			if frappe.db.get_value(doctype, name, df.fieldname) == old_url:
				frappe.db.set_value(doctype, name, df.fieldname, new_url, update_modified=False)
				changed += 1
	for table_df in meta.get_table_fields():
		child = frappe.get_meta(table_df.options)
		for df in child.fields:
			if df.fieldtype not in ATTACH_TYPES:
				continue
			table = frappe.qb.DocType(table_df.options)
			rows = (
				frappe.qb.from_(table)
				.select(table.name)
				.where(table.parent == name)
				.where(table.parenttype == doctype)
				.where(table.parentfield == table_df.fieldname)
				.where(table[df.fieldname] == old_url)
			).run(pluck=True)
			for row in rows:
				frappe.db.set_value(table_df.options, row, df.fieldname, new_url, update_modified=False)
				changed += 1
	return changed


def make_private(file_name):
	"""Move one public File to private/files and rewrite the URLs that pointed
	at it. Returns the moved File, or None when it was left as it was (already
	private, remote, a folder, or shared with a record outside the app)."""
	file_doc = frappe.get_doc("File", file_name)
	if file_doc.is_folder or cint(file_doc.is_private) or not (file_doc.file_url or "").startswith("/files/"):
		return None
	if _shared_elsewhere(file_doc):
		return None

	old_url = file_doc.file_url
	siblings = frappe.get_all(
		"File",
		filters={"file_url": old_url, "name": ["!=", file_doc.name]},
		fields=["attached_to_doctype", "attached_to_name"],
	)
	file_doc.is_private = 1
	file_doc.flags.ignore_permissions = True
	file_doc.save()  # Frappe moves the file and updates File records sharing it
	new_url = file_doc.file_url

	# Siblings that only shared the URL (no content hash) are left by Frappe.
	frappe.db.set_value("File", {"file_url": old_url}, {"file_url": new_url, "is_private": 1}, update_modified=False)
	for owner in [file_doc, *siblings]:
		replace_attach_urls(owner.attached_to_doctype, owner.attached_to_name, old_url, new_url)
	return file_doc


def on_file_insert(doc, method=None):
	"""File after_insert: a public file attached to a freight record goes
	private. The upload override already does this for uploads; this covers
	files made any other way (frappe.client.insert, an Attach field filled
	with a public URL)."""
	if doc.is_folder or cint(doc.is_private) or not is_private_doctype(doc.attached_to_doctype):
		return
	if not (doc.file_url or "").startswith("/files/"):
		return
	try:
		moved = make_private(doc.name)
	except (FileNotFoundError, FileExistsError):
		frappe.log_error(title="R3-10: could not make attachment private", reference_doctype="File", reference_name=doc.name)
		return
	if moved:
		# The caller (upload_file returns this doc) sees where it went, and a
		# rolled-back insert deletes the file where it now is; undoing the
		# move as well would look for a file that is already gone.
		doc.file_url = moved.file_url
		doc.is_private = 1
		moved.flags.pop("original_path", None)
