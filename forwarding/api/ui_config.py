# Copyright (c) 2026, DVNKS Systems and contributors
# For license information, please see license.txt
"""Page and wizard configuration for the Freight LCS front end, read from
custom_ui records.

The Job 360, Customer 360, Supplier 360 and Home pages are bespoke Vue
screens; what they show, in what order and under what label is read from a
Custom UI Dashboard per page:

	Job 360 / Customer 360 / Supplier 360
		Entity rows of the Tabs table	the tabs (tab_key, label, icon,
						is_default; order by sort_order)
		entity_props (JSON)		{"freight_page": "job_360",
						 "tiles": [{key, label, tab, hidden}],
						 "action_groups": [{key, label}],
						 "actions": [{key, label, group, icon, hidden}],
						 "banners": {"max_visible": 3}}
	Freight Home
		entity_props (JSON)		{"freight_page": "home",
						 "sections": [{key, label, hidden}]}

The New Job wizard is the Custom UI Wizard Layout "New Job": its Wizard Field
rows (section = step key) list each step's fields, and its description holds
the step labels, hints and the step saving starts from as JSON:
{"save_from_step": 1, "steps": [{key, label, hint, icon}]}.

Only the keys this module knows (PAGES / WIZARDS below) are sent: anything
else in a record is dropped, since the page has no code for it. Labels can be
renamed freely and order follows the record. A page with no active
dashboard, or one whose JSON does not parse, gets the built-in defaults with
source "default"; nothing here raises on bad config.

A dashboard with Roles set applies only to users with one of them; everyone
else gets the built-in defaults (source "default"), not an empty page.

Both reads are cached for 60 seconds (pages for everyone, wizards per user,
since the wizard drops fields the user cannot read) and dropped whenever a
Custom UI Dashboard or Wizard Layout is saved or deleted (see hooks.py).
"""

import copy
import json

import frappe
from frappe import _
from frappe.utils import cint

CACHE_PREFIX = "ui_config:"
CACHE_SECONDS = 60

DASHBOARD = "Custom UI Dashboard"
WIZARD_LAYOUT = "Custom UI Wizard Layout"

MAX_BANNERS_LIMIT = 20

# -- Built-in defaults, which are also the whitelist of keys per page ---------------
#
# These reproduce the pages as they were hard-coded in the Vue app. The seed
# patch (forwarding.patches.v1_0.seed_ui_config) writes the same into the
# custom_ui records.

PAGES = {
	"job_360": {
		"dashboard": "Job 360",
		"title": "Job 360",
		"entity_doctype": "Operations",
		"tabs": [
			{"key": "overview", "label": "Overview", "icon": None, "is_default": 1},
			{"key": "documents", "label": "Documents", "icon": None, "is_default": 0},
			{"key": "milestones", "label": "Milestones", "icon": None, "is_default": 0},
			{"key": "services", "label": "Services", "icon": None, "is_default": 0},
			{"key": "charges", "label": "Charges", "icon": None, "is_default": 0},
			{"key": "invoices", "label": "Invoices", "icon": None, "is_default": 0},
			{"key": "activity", "label": "Activity", "icon": None, "is_default": 0},
		],
		"tiles": [
			{"key": "documents", "label": "Documents", "tab": "documents"},
			{"key": "services", "label": "Linked services", "tab": "services"},
			{"key": "cost_revenue", "label": "Cost vs revenue", "tab": "charges"},
			{"key": "billed_collected", "label": "Billed / collected", "tab": "invoices"},
			{"key": "free_time", "label": "Free time left", "tab": "milestones"},
		],
		"groups": [
			{"key": "update", "label": "Update"},
			{"key": "print", "label": "Print / Send"},
			{"key": "create", "label": "Create"},
			{"key": "more", "label": "More"},
		],
		"actions": [
			{"key": "record_atd", "label": "Record ATD", "group": "update", "icon": "calendar-check"},
			{"key": "record_ata", "label": "Record ATA", "group": "update", "icon": "calendar-check"},
			{"key": "put_on_hold", "label": "Put on hold", "group": "update", "icon": "circle-pause"},
			{"key": "close_job", "label": "Close job", "group": "update", "icon": "lock"},
			{"key": "print", "label": "Job print", "group": "print", "icon": "printer"},
			{"key": "sales_invoice", "label": "Sales Invoice", "group": "create", "icon": "receipt"},
			{"key": "purchase_invoice", "label": "Purchase Invoice", "group": "create", "icon": "file-text"},
			{"key": "transportation", "label": "Transportation", "group": "create", "icon": "truck"},
			{"key": "custom_clearance", "label": "Custom Clearance", "group": "create", "icon": "shield-check"},
			{"key": "expense_claim", "label": "Expense Claim", "group": "create", "icon": "wallet"},
			{"key": "cancel", "label": "Cancel job", "group": "more", "icon": "ban"},
			{"key": "duplicate", "label": "Duplicate", "group": "more", "icon": "copy"},
			{"key": "audit_log", "label": "Audit log", "group": "more", "icon": "history"},
			{"key": "edit", "label": "Edit", "group": None, "icon": "pencil"},
		],
		"banners": {"max_visible": 3},
	},
	"customer_360": {
		"dashboard": "Customer 360",
		"title": "Customer 360",
		"entity_doctype": "Customer",
		"tabs": [
			{"key": "jobs", "label": "Jobs", "icon": None, "is_default": 1},
			{"key": "quotations", "label": "Quotations", "icon": None, "is_default": 0},
			{"key": "invoices", "label": "Invoices", "icon": None, "is_default": 0},
			{"key": "payments", "label": "Payments", "icon": None, "is_default": 0},
			{"key": "documents", "label": "Documents", "icon": None, "is_default": 0},
			{"key": "contacts", "label": "Contacts & Addresses", "icon": None, "is_default": 0},
			{"key": "activity", "label": "Activity", "icon": None, "is_default": 0},
		],
		"tiles": [
			{"key": "active_jobs", "label": "Active jobs", "tab": "jobs"},
			{"key": "open_quotes", "label": "Open quotations", "tab": "quotations"},
			{"key": "outstanding", "label": "Outstanding", "tab": "invoices"},
			{"key": "credit", "label": "Credit used / limit", "tab": "invoices"},
			{"key": "documents", "label": "Documents on file", "tab": "documents"},
		],
		"groups": [],
		"actions": [
			{"key": "new_quotation", "label": "New Quotation", "group": None, "icon": "file-signature"},
			{"key": "new_job", "label": "New Job", "group": None, "icon": "file-plus-2"},
			{"key": "statement", "label": "Statement of Account", "group": None, "icon": "file-text"},
			{"key": "edit", "label": "Edit", "group": None, "icon": "pencil"},
		],
		"banners": {"max_visible": 3},
	},
	"supplier_360": {
		"dashboard": "Supplier 360",
		"title": "Supplier 360",
		"entity_doctype": "Supplier",
		"tabs": [
			{"key": "jobs", "label": "Jobs", "icon": None, "is_default": 1},
			{"key": "services", "label": "Services", "icon": None, "is_default": 0},
			{"key": "purchase_invoices", "label": "Purchase Invoices", "icon": None, "is_default": 0},
			{"key": "payments", "label": "Payments", "icon": None, "is_default": 0},
			{"key": "documents", "label": "Documents", "icon": None, "is_default": 0},
			{"key": "contacts", "label": "Contacts & Addresses", "icon": None, "is_default": 0},
			{"key": "activity", "label": "Activity", "icon": None, "is_default": 0},
		],
		"tiles": [
			{"key": "active_jobs", "label": "Active jobs", "tab": "jobs"},
			# Open services moved under Active jobs as a sub-line (Phase 2 SU4).
			{"key": "cost_variance", "label": "Cost variance", "tab": "jobs"},
			{"key": "payables", "label": "Payables outstanding", "tab": "purchase_invoices"},
			{"key": "billed_year", "label": "Billed this year", "tab": "purchase_invoices"},
			{"key": "documents", "label": "Documents on file", "tab": "documents"},
		],
		"groups": [],
		"actions": [
			{"key": "new_purchase_invoice", "label": "New Purchase Invoice", "group": None, "icon": "receipt"},
			{"key": "statement", "label": "Statement of Account", "group": None, "icon": "file-text"},
			{"key": "edit", "label": "Edit", "group": None, "icon": "pencil"},
		],
		"banners": {"max_visible": 3},
	},
	"home": {
		"dashboard": "Freight Home",
		"title": "Freight Home",
		"entity_doctype": None,
		"sections": [
			{"key": "checklist", "label": "Set up your workspace"},
			{"key": "worklist", "label": "Worklist"},
			{"key": "kpis", "label": "Key figures"},
			{"key": "modules", "label": "Workspace modules"},
			{"key": "billing_pipeline", "label": "Billing pipeline"},
		],
	},
}

WIZARDS = {
	"New Job": {
		"target_doctype": "Operations",
		"save_from_step": 1,
		"steps": [
			{
				"key": "basics",
				"label": "Basics",
				"icon": "layers",
				"hint": "What kind of job this is. Branch, type and mode decide its number.",
				"fields": ["branch", "job_type", "mode_of_shipment", "shipment_type", "activity_code", "inco_terms"],
			},
			{
				"key": "parties",
				"label": "Parties",
				"icon": "user",
				"hint": "Who the job is for. A draft can be saved from here on.",
				"fields": ["customer", "consignee", "shipper", "salesman", "po_no"],
			},
			{
				"key": "route",
				"label": "Route",
				"icon": "map-pin",
				"hint": "Where it goes, on what, and when.",
				"fields": [
					"port_of_loading",
					"port_of_destination",
					"shipping_line",
					"air_line",
					"vessel_name",
					"flight_number",
					"awb_number",
					"etd_date",
					"eta_date",
					"free_time_days",
				],
			},
			{
				"key": "cargo",
				"label": "Cargo",
				"icon": "package",
				"hint": "What is shipped. Containers are added on the job once it is saved.",
				"fields": ["commodity", "packages", "net_weight", "gross_weight", "weight_uom", "cbm", "cargo_description"],
			},
		],
		# Labels the wizard shows in place of the DocType's own.
		"labels": {"activity_code": "Service Type"},
	},
}


# -- Endpoints ------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_page(page: str) -> dict:
	"""The configuration of one bespoke page: job_360, customer_360,
	supplier_360 or home. See the module docstring for the shape."""
	_require_login()
	if page not in PAGES:
		frappe.throw(_("Unknown page {0}").format(frappe.bold(page)), frappe.ValidationError)

	key = f"{CACHE_PREFIX}page:{page}"
	cached = frappe.cache.get_value(key)
	if cached is None:
		cached = _resolve_page(page)
		frappe.cache.set_value(key, cached, expires_in_sec=CACHE_SECONDS)

	roles = cached.get("roles") or []
	if roles and not set(roles) & set(frappe.get_roles()):
		return default_page(page)
	return copy.deepcopy(cached["payload"])


@frappe.whitelist(methods=["GET"])
def get_wizard(name: str = "New Job") -> dict:
	"""The steps of a front-end wizard and the fields on each.

	{"wizard", "source", "save_from_step",
	 "steps": [{"key", "label", "hint", "icon",
		    "fields": [{"fieldname", "label", "hidden", "read_only"}]}]}

	Fields come from the Custom UI Wizard Layout (via custom_ui's own
	get_wizard_layout, which drops fields the user cannot read); a step the
	layout has no rows for keeps its built-in fields."""
	_require_login()
	if name not in WIZARDS:
		frappe.throw(_("Unknown wizard {0}").format(frappe.bold(name)), frappe.ValidationError)

	key = f"{CACHE_PREFIX}wizard:{name}:{frappe.session.user}"
	cached = frappe.cache.get_value(key)
	if cached is None:
		cached = _resolve_wizard(name)
		frappe.cache.set_value(key, cached, expires_in_sec=CACHE_SECONDS)
	return copy.deepcopy(cached)


def clear_cache(doc=None, method=None):
	"""doc_events hook: a Custom UI record the pages read changed."""
	frappe.cache.delete_keys(CACHE_PREFIX)


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Log in to read the page configuration"), frappe.PermissionError)


# -- Pages ------------------------------------------------------------------------------


def default_page(page):
	spec = PAGES[page]
	out = {"page": page, "dashboard": spec["dashboard"], "source": "default"}
	if page == "home":
		out["sections"] = [dict(s) for s in spec["sections"]]
		return out
	out["tabs"] = [dict(t) for t in spec["tabs"]]
	out["tiles"] = [dict(t) for t in spec["tiles"]]
	out["groups"] = [dict(g) for g in spec["groups"]]
	out["actions"] = [dict(a) for a in spec["actions"]]
	out["banners"] = dict(spec["banners"])
	return out


def _find_dashboard(page):
	"""The active Custom UI Dashboard for page: the one whose entity_props
	say "freight_page": page, else the one with the default name."""
	spec = PAGES[page]
	for name in frappe.get_all(DASHBOARD, filters={"is_active": 1}, pluck="name", order_by="name asc"):
		raw = frappe.db.get_value(DASHBOARD, name, "entity_props")
		try:
			props = json.loads(raw or "{}")
		except ValueError:
			continue
		if isinstance(props, dict) and props.get("freight_page") == page:
			return name
	return frappe.db.get_value(DASHBOARD, {"name": spec["dashboard"], "is_active": 1})


def _resolve_page(page):
	"""{"roles": [...], "payload": {...}}, the role-independent part."""
	try:
		name = _find_dashboard(page)
		if not name:
			return {"roles": [], "payload": default_page(page)}
		doc = frappe.get_doc(DASHBOARD, name)
		props = json.loads(doc.entity_props or "{}")
		if not isinstance(props, dict):
			raise ValueError("entity_props is not a JSON object")
		payload = _page_from_dashboard(page, doc, props)
	except Exception:
		# A broken record must never take the page down: log it and serve
		# the built-in page.
		frappe.log_error(title=f"UI config for {page} could not be read", reference_doctype=DASHBOARD)
		return {"roles": [], "payload": default_page(page)}
	return {"roles": [r.role for r in doc.get("roles") or [] if r.role], "payload": payload}


def _page_from_dashboard(page, doc, props):
	spec = PAGES[page]
	out = {"page": page, "dashboard": doc.name, "source": "custom_ui"}
	if page == "home":
		out["sections"] = _entries(props.get("sections"), spec["sections"], ("label",))
		return out

	tabs = _tabs(doc, spec)
	tab_keys = {t["key"] for t in tabs}
	out["tabs"] = tabs

	default_tile_tabs = {t["key"]: t["tab"] for t in spec["tiles"]}
	tiles = _entries(props.get("tiles"), spec["tiles"], ("label",))
	for tile, raw in zip(tiles, _raw_by_key(props.get("tiles"), tiles)):
		wanted = raw.get("tab") if isinstance(raw, dict) and raw.get("tab") else default_tile_tabs[tile["key"]]
		tile["tab"] = wanted if wanted in tab_keys else None
	out["tiles"] = tiles

	groups = _entries(props.get("action_groups"), spec["groups"], ("label",))
	group_keys = {g["key"] for g in groups}
	default_groups = {a["key"]: a["group"] for a in spec["actions"]}
	actions = _entries(props.get("actions"), spec["actions"], ("label", "icon"))
	for action, raw in zip(actions, _raw_by_key(props.get("actions"), actions)):
		group = raw["group"] if isinstance(raw, dict) and "group" in raw else default_groups[action["key"]]
		if group and group not in group_keys:
			group = default_groups[action["key"]] if default_groups[action["key"]] in group_keys else None
		action["group"] = group or None
	used = {a["group"] for a in actions}
	out["groups"] = [g for g in groups if g["key"] in used]
	out["actions"] = actions

	banners = props.get("banners") if isinstance(props.get("banners"), dict) else {}
	max_visible = banners.get("max_visible", spec["banners"]["max_visible"])
	try:
		max_visible = max(0, min(MAX_BANNERS_LIMIT, int(max_visible)))
	except (TypeError, ValueError):
		max_visible = spec["banners"]["max_visible"]
	out["banners"] = {"max_visible": max_visible}
	return out


def _entries(configured, defaults, overridable):
	"""configured (a list from entity_props) filtered to the keys in defaults,
	in configured order, hidden ones dropped, each with the default's fields
	and the overridable ones taken from configured when set. Anything that is
	not a list means "not configured": the defaults."""
	if not isinstance(configured, list):
		return [dict(d) for d in defaults]
	by_key = {d["key"]: d for d in defaults}
	out, seen = [], set()
	for item in configured:
		if not isinstance(item, dict):
			continue
		key = item.get("key")
		if not isinstance(key, str) or key not in by_key or key in seen:
			continue
		seen.add(key)
		if item.get("hidden"):
			continue
		entry = dict(by_key[key])
		for field in overridable:
			value = item.get(field)
			if isinstance(value, str) and value.strip():
				entry[field] = value.strip()
		out.append(entry)
	return out


def _raw_by_key(configured, entries):
	"""The configured item behind each entry, in the entries' order."""
	if not isinstance(configured, list):
		return [{} for _e in entries]
	by_key = {}
	for item in configured:
		if isinstance(item, dict) and isinstance(item.get("key"), str):
			by_key.setdefault(item["key"], item)
	return [by_key.get(e["key"], {}) for e in entries]


def _tabs(doc, spec):
	"""The Entity rows of the dashboard's Tabs table, in sort_order, limited
	to the page's tab keys. No usable row means "not configured": defaults."""
	by_key = {t["key"]: t for t in spec["tabs"]}
	rows = [r for r in doc.get("tabs") or [] if r.tab_group == "Entity"]
	rows.sort(key=lambda r: (cint(r.sort_order), cint(r.idx)))
	out, seen = [], set()
	for row in rows:
		key = (row.tab_key or "").strip()
		if key not in by_key or key in seen:
			continue
		seen.add(key)
		out.append(
			{
				"key": key,
				"label": (row.label or "").strip() or by_key[key]["label"],
				"icon": (row.icon or "").strip() or by_key[key]["icon"],
				"is_default": 1 if row.is_default else 0,
			}
		)
	if not out:
		return [dict(t) for t in spec["tabs"]]
	first_default = next((t for t in out if t["is_default"]), out[0])
	for tab in out:
		tab["is_default"] = 1 if tab is first_default else 0
	return out


# -- Wizards -----------------------------------------------------------------------------


def default_wizard(name):
	spec = WIZARDS[name]
	meta = frappe.get_meta(spec["target_doctype"])
	return {
		"wizard": name,
		"source": "default",
		"save_from_step": spec["save_from_step"],
		"steps": [
			{
				"key": step["key"],
				"label": step["label"],
				"hint": step["hint"],
				"icon": step["icon"],
				"fields": _default_fields(step, spec, meta),
			}
			for step in spec["steps"]
		],
	}


def _default_fields(step, spec, meta):
	out = []
	for fieldname in step["fields"]:
		df = meta.get_field(fieldname)
		if not df:
			continue  # a site without the field: skip it, as the wizard does
		out.append(
			{
				"fieldname": fieldname,
				"label": spec["labels"].get(fieldname) or (df.label or fieldname).strip(),
				"hidden": 0,
				"read_only": 0,
			}
		)
	return out


def _resolve_wizard(name):
	from custom_ui.api import get_wizard_layout

	spec = WIZARDS[name]
	try:
		if not frappe.db.exists(WIZARD_LAYOUT, {"wizard": name, "is_active": 1}):
			return default_wizard(name)
		layout = get_wizard_layout(name)
		description = frappe.db.get_value(WIZARD_LAYOUT, {"wizard": name}, "description")
		return _wizard_from_layout(name, spec, layout.get("sections") or {}, description)
	except Exception:
		frappe.log_error(title=f"UI config for wizard {name} could not be read", reference_doctype=WIZARD_LAYOUT)
		return default_wizard(name)


def _wizard_meta(description):
	"""The step settings JSON in the Wizard Layout's description, or {}."""
	try:
		value = json.loads(description or "{}")
	except ValueError:
		return {}
	return value if isinstance(value, dict) else {}


def _wizard_from_layout(name, spec, sections, description):
	settings = _wizard_meta(description)
	step_settings = {}
	for item in settings.get("steps") if isinstance(settings.get("steps"), list) else []:
		if isinstance(item, dict) and isinstance(item.get("key"), str):
			step_settings.setdefault(item["key"], item)

	meta = frappe.get_meta(spec["target_doctype"])
	steps = []
	for step in spec["steps"]:
		custom = step_settings.get(step["key"], {})
		rows = [r for r in sections.get(step["key"]) or [] if r.get("doctype") == spec["target_doctype"]]
		fields = _layout_fields(rows, spec, meta) if step["key"] in sections else _default_fields(step, spec, meta)
		steps.append(
			{
				"key": step["key"],
				"label": _text(custom.get("label")) or step["label"],
				"hint": _text(custom.get("hint")) or step["hint"],
				"icon": _text(custom.get("icon")) or step["icon"],
				"fields": fields,
			}
		)

	try:
		save_from = int(settings.get("save_from_step", spec["save_from_step"]))
	except (TypeError, ValueError):
		save_from = spec["save_from_step"]
	save_from = max(0, min(len(steps) - 1, save_from))
	return {"wizard": name, "source": "custom_ui", "save_from_step": save_from, "steps": steps}


def _layout_fields(rows, spec, meta):
	out, seen = [], set()
	for row in rows:
		fieldname = row["fieldname"]
		df = meta.get_field(fieldname)
		if not df or fieldname in seen:
			continue
		seen.add(fieldname)
		out.append(
			{
				"fieldname": fieldname,
				"label": row.get("label") or spec["labels"].get(fieldname) or (df.label or fieldname).strip(),
				# custom_ui refuses to save a hidden mandatory field; a field
				# made mandatory afterwards is shown anyway, or the step could
				# never be finished.
				"hidden": 0 if df.reqd else cint(row.get("hidden")),
				"read_only": cint(row.get("read_only")),
			}
		)
	return out


def _text(value):
	return value.strip() if isinstance(value, str) and value.strip() else None
