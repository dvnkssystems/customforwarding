# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Report a bug from the app (A-47).

submit() always saves an App Bug Report (the screenshot as a private File on
it). When site config names a repository and a token, it also queues a job
that raises a GitHub issue and stores the issue's URL back on the record:

	bench --site <site> set-config github_bug_repo "dvnkssystems/freight_lcs_vue"
	bench --site <site> set-config github_bug_token "<fine-grained token, Issues: read and write>"

GitHub's REST API cannot take an image upload, and it cannot read the site's
private files, so the issue carries a link to the screenshot on the site; it
opens for someone signed in there.
"""

import base64
import re

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, get_url, now_datetime

MAX_SUBJECT = 140
MAX_MESSAGE = 5000
MAX_PAGE = 1000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Reports one user may send in an hour; past that it is a loop or a script.
MAX_PER_HOUR = 10
IMAGE_TYPES = {"png": b"\x89PNG", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "gif": b"GIF8", "webp": b"RIFF"}
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
TIMEOUT = 20
NO_MENTION = "@\u200b"


@frappe.whitelist(methods=["POST"])
def submit(subject, message, page=None, image=None, image_name=None):
	"""{name, github}: the saved report, and "queued" or "not_configured".

	`image` is the screenshot's base64 content (a data: URL is fine) and
	`image_name` its file name."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Sign in to report a bug"), frappe.PermissionError)
	subject = (subject or "").strip()
	message = (message or "").strip()
	page = (page or "").strip()
	if not subject or not message:
		frappe.throw(_("Enter a subject and a message"))
	if len(subject) > MAX_SUBJECT:
		frappe.throw(_("Keep the subject to {0} characters").format(MAX_SUBJECT))
	if len(message) > MAX_MESSAGE:
		frappe.throw(_("Keep the message to {0} characters").format(MAX_MESSAGE))
	if len(page) > MAX_PAGE:
		page = page[:MAX_PAGE]
	recent = frappe.db.count(
		"App Bug Report",
		{"owner": frappe.session.user, "creation": (">", add_to_date(now_datetime(), hours=-1))},
	)
	if recent >= MAX_PER_HOUR:
		frappe.throw(_("You have sent {0} reports in the last hour. Try again later.").format(recent))
	content, filename = decode_image(image, image_name) if image else (None, None)

	doc = frappe.get_doc(
		{
			"doctype": "App Bug Report",
			"subject": subject,
			"message": message,
			"page": page,
			"reported_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	if content:
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"attached_to_doctype": "App Bug Report",
				"attached_to_name": doc.name,
				"attached_to_field": "image",
				"is_private": 1,
				"content": content,
			}
		).insert(ignore_permissions=True)
		doc.db_set("image", file.file_url)

	if not github_config():
		return {"name": doc.name, "github": "not_configured"}
	doc.db_set("github_status", "Queued")
	if not frappe.flags.in_test:
		frappe.enqueue(
			"forwarding.api.bug_report.create_github_issue",
			name=doc.name,
			queue="short",
			timeout=120,
			enqueue_after_commit=True,
		)
	return {"name": doc.name, "github": "queued"}


def decode_image(data, name):
	"""(bytes, safe file name) of an uploaded screenshot, or a ValidationError."""
	if "," in data[:100] and data.startswith("data:"):
		data = data.split(",", 1)[1]
	if len(data) > MAX_IMAGE_BYTES * 4 // 3 + 4:
		frappe.throw(_("The image is larger than {0} MB").format(MAX_IMAGE_BYTES // (1024 * 1024)))
	try:
		content = base64.b64decode(data, validate=True)
	except Exception:
		frappe.throw(_("The image could not be read"))
	ext = (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""
	magic = IMAGE_TYPES.get(ext)
	if not magic or not content.startswith(magic):
		frappe.throw(_("Attach a PNG, JPG, GIF or WebP image"))
	if len(content) > MAX_IMAGE_BYTES:
		frappe.throw(_("The image is larger than {0} MB").format(MAX_IMAGE_BYTES // (1024 * 1024)))
	stem = re.sub(r"[^\w.-]+", "-", name.rsplit(".", 1)[0]).strip("-.")[:60] or "screenshot"
	return content, f"{stem}.{ext}"


def github_config():
	"""(repo, token) from site config, or None when either is missing."""
	repo = (frappe.conf.get("github_bug_repo") or "").strip()
	token = (frappe.conf.get("github_bug_token") or "").strip()
	if not repo or not token or not REPO.match(repo):
		return None
	return repo, token


def create_github_issue(name):
	"""The background job submit() queues. Never calls out under test."""
	if frappe.flags.in_test:
		return
	push_to_github(name)


def push_to_github(name):
	"""Raise the issue for one report and record how it went."""
	doc = frappe.get_doc("App Bug Report", name)
	config = github_config()
	if not config:
		doc.db_set({"github_status": "Not Configured", "github_error": None})
		return
	repo, token = config
	try:
		response = requests.post(
			f"https://api.github.com/repos/{repo}/issues",
			json={"title": f"[App] {doc.subject}", "body": issue_body(doc), "labels": ["bug"]},
			headers={
				"Authorization": f"Bearer {token}",
				"Accept": "application/vnd.github+json",
				"X-GitHub-Api-Version": "2022-11-28",
				"User-Agent": "freight-lcs-bug-report",
			},
			timeout=TIMEOUT,
		)
	except requests.RequestException as e:
		doc.db_set({"github_status": "Failed", "github_error": f"{e.__class__.__name__}: {e}"[:500]})
		return
	if response.status_code == 201:
		doc.db_set({"github_status": "Created", "github_issue_url": response.json().get("html_url"), "github_error": None})
		return
	try:
		detail = response.json().get("message") or ""
	except ValueError:
		detail = response.text[:200]
	doc.db_set({"github_status": "Failed", "github_error": f"GitHub {response.status_code}: {detail}"[:500]})


def issue_body(doc):
	page = doc.page or ""
	link = page if re.match(r"^https?://", page) else (get_url(page) if page else "")
	user = frappe.db.get_value("User", doc.reported_by, ["full_name", "email"], as_dict=True) or {}
	# @ is broken with a zero-width space so nothing in the issue mentions
	# (notifies) anyone on GitHub.
	who = f"{user.get('full_name') or doc.reported_by} ({user.get('email') or doc.reported_by})".replace("@", NO_MENTION)
	quoted = "\n".join(f"> {line}" for line in (doc.message or "").replace("@", NO_MENTION).splitlines())
	lines = [
		f"**Page:** {link or '—'}",
		f"**Reported by:** {who}",
		f"**Site record:** {get_url(f'/app/app-bug-report/{doc.name}')}",
		"",
		"### Message",
		quoted,
	]
	if doc.image:
		lines += [
			"",
			"### Screenshot",
			f"{get_url(doc.image)}",
			"_A private file on the site: it opens for someone signed in there. GitHub cannot show it inline._",
		]
	return "\n".join(lines)
