# -*- coding: utf-8 -*-
# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
# Used by make_sales_invoice / make_purchase_invoice below; was referenced
# without being imported, so those raised NameError at runtime.
from frappe.model.utils import get_fetch_values
from frappe.utils import cstr, flt, getdate, cint, nowdate, add_days, get_link_to_form, strip_html, get_datetime, now_datetime
from frappe.contacts.doctype.address.address import get_company_address
from erpnext.stock.doctype.item.item import get_item_defaults
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults

from forwarding.child_tables import undate_unreceived_documents, job_containers, add_clearance_containers
# A job's Services, its tick-boxes and which codes it may hold (M-05, M-06).
from forwarding.services import apply_services

# kg per cubic metre for air freight volumetric weight (IATA 1:6000)
AIR_VOLUMETRIC_FACTOR = 167


def get_cutoff_status(latest):
	"""Upcoming, Due Today or Passed for a cut-off's latest time."""
	if not latest:
		return None
	latest = get_datetime(latest)
	now = now_datetime()
	if latest < now:
		return "Passed"
	if latest.date() == now.date():
		return "Due Today"
	return "Upcoming"


# Cut-off milestones, in the order the Job Cutoff options list them.
AES_DEADLINE = "AES Deadline"
SEA_CUTOFFS = ("Rail Cut-off", "Inland Cut-off", "Container Pickup", AES_DEADLINE, "SI Deadline", "Cargo Cut-off")
AIR_CUTOFFS = ("SI Deadline", "Cargo Cut-off")

# destination_country links to Territory; these are the names the US goes by.
US_NAMES = {"united states", "united states of america", "usa", "us"}


def is_us(country):
	return cstr(country).strip().lower() in US_NAMES


def shipment_mode(mode_of_shipment):
	"""Sea, Air or None. The old SEA-FCL / SEA-LCL modes count as Sea."""
	mode = cstr(mode_of_shipment).strip().lower()
	if mode.startswith("sea"):
		return "Sea"
	if mode == "air":
		return "Air"
	return None


def default_cutoff_milestones(mode_of_shipment, destination_country=None):
	"""Cut-offs an export job starts with: every Sea milestone (AES only for
	the United States), or SI Deadline and Cargo Cut-off for Air."""
	mode = shipment_mode(mode_of_shipment)
	if mode == "Sea":
		return [m for m in SEA_CUTOFFS if m != AES_DEADLINE or is_us(destination_country)]
	if mode == "Air":
		return list(AIR_CUTOFFS)
	return []


SERVICE_FIELDS = (
	"svc_freight_forwarding",
	"svc_customs_clearance",
	"svc_transportation",
	"svc_packing_relocation",
	"svc_trading",
	"svc_warehousing",
)


# Masters a job's document checklist is built from on insert, as
# (job field, master DocType). A master counts once it has a Table field of
# Document Table (Shipment Type has one; Freight Activity Code does not yet,
# so adding one as a Custom Field is enough to make it count). Activity
# Template is matched by the job's job_type and mode_of_shipment instead of a
# link; it has no document table today either.
DOCUMENT_SOURCES = (
	("shipment_type", "Shipment Type"),
	("activity_code", "Freight Activity Code"),
)
DOCUMENT_TEMPLATE_DOCTYPE = "Activity Template"


ACTUAL_DATE_FIELDS = ("atd_date", "ata_date")


def validate_actual_dates(doc, fields=ACTUAL_DATE_FIELDS):
	"""Refuse an actual date after today in the site's time zone."""
	today = getdate(nowdate())
	for fieldname in fields:
		value = doc.get(fieldname)
		if not value or getdate(value) <= today:
			continue
		if not (doc.is_new() or doc.has_value_changed(fieldname)):
			continue
		frappe.throw(
			_("{0} cannot be after today ({1}): it records what has already happened.").format(
				_(doc.meta.get_label(fieldname)), frappe.format(today, "Date")
			),
			title=_("Date in the future"),
		)


def document_table_field(doctype):
	"""Fieldname of the doctype's Document Table, or None."""
	if not frappe.db.exists("DocType", doctype):
		return None
	for df in frappe.get_meta(doctype).get_table_fields():
		if df.options == "Document Table":
			return df.fieldname
	return None


def expected_documents(job):
	"""(document, stage) pairs the job's masters expect, in order, once each."""
	sources = []
	for fieldname, doctype in DOCUMENT_SOURCES:
		if job.get(fieldname) and document_table_field(doctype):
			sources.append((doctype, job.get(fieldname)))

	if document_table_field(DOCUMENT_TEMPLATE_DOCTYPE):
		# A template applies when each of its job_type / mode_of_shipment is
		# blank or matches the job's.
		for t in frappe.get_all(
			DOCUMENT_TEMPLATE_DOCTYPE, fields=["name", "job_type", "mode_of_shipment"], order_by="name"
		):
			if all(not t.get(f) or t.get(f) == job.get(f) for f in ("job_type", "mode_of_shipment")):
				sources.append((DOCUMENT_TEMPLATE_DOCTYPE, t.name))

	seen, out = set(), []
	for doctype, name in sources:
		master = frappe.get_cached_doc(doctype, name)
		for row in master.get(document_table_field(doctype)) or []:
			key = (row.document, cstr(row.stage).strip())
			if row.document and key not in seen:
				seen.add(key)
				out.append(key)
	return out


@frappe.whitelist()
def default_expense_account(item, company=None):
	"""The expense account a cost row for `item` books to: the item's default
	for the company, else its item group's, else the company's default
	expense account. None when there is none."""
	if not item:
		return None
	company = company or frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		return None
	return (
		get_item_defaults(item, company).get("expense_account")
		or get_item_group_defaults(item, company).get("expense_account")
		or frappe.get_cached_value("Company", company, "default_expense_account")
	)


class Operations(Document):
	def before_insert(self):
		self.set_default_cutoffs()
		self.set_document_checklist()

	def set_default_cutoffs(self):
		"""An export job starts with its mode's cut-off milestones, undated
		(Sea: Rail, Inland, Container Pickup, SI, Cargo, plus AES when bound
		for the United States; Air: SI and Cargo). Rows already given -- the
		desk form adds the same ones -- are left as they are."""
		if self.job_type != "Export" or self.get("cutoffs"):
			return
		country = self.destination_country or (
			frappe.db.get_value("Port", self.port_of_destination, "country") if self.port_of_destination else None
		)
		for milestone in default_cutoff_milestones(self.mode_of_shipment, country):
			self.append("cutoffs", {"milestone": milestone})

	def set_document_checklist(self):
		"""Add the documents the job's masters expect (expected_documents) as
		not-yet-received rows, skipping any the job already lists."""
		listed = {(r.document, cstr(r.stage).strip()) for r in self.get("document_table") or []}
		listed_names = {r.document for r in self.get("document_table") or []}
		for document, stage in expected_documents(self):
			if (document, stage) in listed or (not stage and document in listed_names):
				continue
			self.append("document_table", {"document": document, "stage": stage or None, "received": "No"})

	def before_validate(self):
		from forwarding.quote_to_job import commodity_from_quote, parties_from_quote

		commodity_from_quote(self)
		parties_from_quote(self)

	def validate(self):
		self.set_company()
		self.set_operation_id()
		self.validate_shipment_type()
		apply_services(self)
		self.validate_ports()
		self.calculate_package_totals()
		self.validate_weights()
		self.validate_actual_dates()
		self.set_default_salesman()
		self.set_free_time_expiry()
		self.set_chargeable_weight()
		self.validate_cutoffs()
		self.set_cutoff_status()
		self.sync_container_rows()
		self.set_billing_status()
		self.set_cost_accounts()
		self.warn_missing_documents()

	def before_submit(self):
		self.validate_estimate()

	def validate_estimate(self):
		"""A job is submitted with its estimate (M-02): at least one cost sheet
		row with an Est. Selling above zero. A draft saves without one."""
		from forwarding.banners import has_estimate

		if not has_estimate(self):
			frappe.throw(_("Add an estimate before submitting"), title=_("Estimate missing"))

	def before_update_after_submit(self):
		"""Ops keep a submitted job current (schedule, cut-offs, containers,
		documents): those fields are Allow on Submit. Re-derive what follows
		from them, as validate does for a draft."""
		self.validate_actual_dates()
		self.set_free_time_expiry()
		self.validate_cutoffs()
		self.set_cutoff_status()
		self.sync_container_rows()

	def on_update_after_submit(self):
		self.sync_clearance_containers()

	def onload(self):
		# Stored statuses age with the clock; show them as of now.
		self.set_cutoff_status()

	def warn_missing_documents(self):
		"""Say which documents the job is still waiting on, without blocking it.

		Two things count as outstanding: one the Shipment Type expects that the
		job does not list at all, and one the job lists but has not marked
		received.

		Deliberately a warning. A job is opened long before its paperwork
		arrives, so refusing to save would stop the work rather than help it --
		and a job that cannot be saved cannot record the document either.

		A Shipment Type with no documents set expects nothing, so a job only
		hears about rows it already carries. That keeps the jobs filed before
		this existed quiet until someone configures the type.
		"""
		if self.docstatus == 2:
			return

		listed = {}
		for row in self.get("document_table") or []:
			if row.document:
				listed[row.document] = cstr(row.received).strip()

		expected = []
		if self.shipment_type:
			# Read the type's own rows rather than querying the child table
			# directly: that needs the parent doctype declared, and the keyword
			# for it has moved between Frappe versions.
			shipment_type = frappe.get_cached_doc("Shipment Type", self.shipment_type)
			expected = [row.document for row in shipment_type.get("document_table") or [] if row.document]

		missing = [name for name in expected if name and name not in listed]
		awaited = [name for name, received in listed.items() if received != "Yes"]

		lines = []
		if missing:
			lines.append(_("Not on the job yet: {0}").format(", ".join(frappe.bold(n) for n in missing)))
		if awaited:
			lines.append(_("Not marked received: {0}").format(", ".join(frappe.bold(n) for n in awaited)))

		if lines:
			frappe.msgprint("<br>".join(lines), title=_("Documents outstanding"), indicator="orange")

	def set_company(self):
		"""Fill an empty company from the user's default, then the site's.

		The DocType used to default to one client's company by name, which
		blocked every new job on any site that does not have that company.
		"""
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
				"Global Defaults", "default_company"
			)

	def set_operation_id(self):
		"""Operation ID is the job number, not something typed in."""
		self.operation_id = self.name

	def validate_ports(self):
		"""A shipment cannot leave from the port it is bound for.

		Checked on every save, so a job saved before this rule has to be
		corrected before anything else on it is. Only a freight forwarding job
		moves cargo between two ports: a customs-only or local transport job
		can name one location for both.
		"""
		# `freight_forwarding` is the old service flag, still "1" on older jobs.
		if not (cint(self.svc_freight_forwarding) or cstr(self.freight_forwarding) == "1"):
			return
		if not self.port_of_loading or self.port_of_loading != self.port_of_destination:
			return
		frappe.throw(
			_("Port of Loading and Port of Discharge are both {0}. Choose a different port for one of them.").format(
				frappe.bold(self.port_of_loading)
			),
			title=_("Same origin and destination"),
		)

	def validate_actual_dates(self):
		"""ATD and ATA record what has happened, so neither can be after today
		(the site's day, System Settings time zone).

		Only a date set or changed in this save is checked: a job saved before
		this rule is not blocked over a date nobody touched."""
		validate_actual_dates(self)

	def validate_weights(self):
		"""Gross weight includes the packing, so it cannot be below the net
		weight. Checked only when both are filled, and only when one of them
		changed in this save."""
		gross, net = flt(self.gross_weight), flt(self.net_weight)
		if not (gross > 0 and net > 0) or gross >= net:
			return
		if not (self.is_new() or self.has_value_changed("gross_weight") or self.has_value_changed("net_weight")):
			return
		frappe.throw(
			_("Gross weight ({0}) cannot be less than net weight ({1}). Gross weight includes the packing.").format(
				frappe.format(gross, "Float"), frappe.format(net, "Float")
			),
			title=_("Check the cargo weights"),
		)

	def set_default_salesman(self):
		"""A new job, or one whose customer changed, with no Salesman takes the
		customer's Default Salesperson. One chosen on the job is kept."""
		if self.salesman or not self.customer:
			return
		if not (self.is_new() or self.has_value_changed("customer")):
			return
		from forwarding.api.customer_360 import customer_default_salesperson

		self.salesman = customer_default_salesperson(self.customer)

	def validate_shipment_type(self):
		"""Shipment Type must be one offered for the job's Mode of Shipment.

		Only checked when either field changes, so jobs saved before the list was
		tied to modes can still be edited without being forced to fix it.
		"""
		if not self.shipment_type or not self.mode_of_shipment:
			return
		if not (self.has_value_changed("shipment_type") or self.has_value_changed("mode_of_shipment")):
			return

		mode, disabled = frappe.db.get_value(
			"Shipment Type", self.shipment_type, ["mode_of_shipment", "disabled"]) or (None, 0)
		if disabled:
			frappe.throw(_("Shipment Type {0} is no longer in use.").format(frappe.bold(self.shipment_type)))
		if mode and mode != self.mode_of_shipment:
			frappe.throw(_("Shipment Type {0} is for {1} shipments, not {2}.").format(
				frappe.bold(self.shipment_type), frappe.bold(mode), frappe.bold(self.mode_of_shipment)))

	def calculate_package_totals(self):
		"""Roll the package grid up into the Package tab totals.

		Per row, the same way the Bridge LCS package grid does:
		volume = qty x (L x W x H) / 1e6, the row's total m3 (dimensions in cm);
		total weight = qty x weight; chargeable weight = the greater of the
		total weight and volume x 167 (IATA 1:6000). The total chargeable
		weight is the sum of the rows, not the rule applied to the totals.
		"""
		qty = volume = weight = chargeable = 0.0

		for row in self.get("package_details") or []:
			row.volume = flt(row.quantity) * (
				flt(row.length) * flt(row.width) * flt(row.height)) / 1000000.0
			row.total_weight = flt(row.quantity) * flt(row.weight)
			row.chargeable_weight = max(flt(row.total_weight), flt(row.volume) * AIR_VOLUMETRIC_FACTOR)

			qty += flt(row.quantity)
			volume += flt(row.volume)
			weight += flt(row.total_weight)
			chargeable += flt(row.chargeable_weight)

		self.total_package_qty = qty
		self.total_package_volume = volume
		self.total_package_weight = weight
		self.total_chargeable_weight = chargeable
		self.set_cargo_from_packages()

	def set_cargo_from_packages(self):
		"""With package rows, the header cargo figures are the rows' totals.

		The form makes them read-only while rows exist (read_only_depends_on),
		so the header and the grid cannot disagree. A job without package rows
		-- a container job, or one keyed in by weight -- keeps what was typed.
		"""
		if not self.get("package_details"):
			return
		pieces = flt(self.total_package_qty)
		self.packages = f"{pieces:g}"
		self.no_of_pieces = cint(round(pieces))
		self.gross_weight = flt(self.total_package_weight)
		self.cbm = flt(self.total_package_volume, 3)
		self.volume = flt(self.total_package_volume, 3)
		self.chargable_weight = flt(self.total_chargeable_weight)

	def set_free_time_expiry(self):
		"""Free time runs from arrival: the ATA once recorded, the ETA until then."""
		days = cint(self.free_time_days)
		start = self.ata_date or self.eta_date
		self.free_time_expiry = add_days(start, days) if start and days > 0 else None

	def set_chargeable_weight(self):
		"""Air freight bills the greater of actual and volumetric weight.

		Volumetric weight is CBM x 167 kg (IATA 1:6000). Other modes keep
		whatever was typed in, since there is no single rule for them.
		"""
		if self.mode_of_shipment != "Air" or self.get("package_details"):
			# With package rows it is their total (set_cargo_from_packages).
			return
		if not (flt(self.gross_weight) or flt(self.cbm)):
			return
		self.chargable_weight = max(flt(self.gross_weight), flt(self.cbm) * AIR_VOLUMETRIC_FACTOR)

	def validate_cutoffs(self):
		"""AES filing only applies to shipments bound for the United States."""
		if is_us(self.destination_country):
			return
		for row in self.get("cutoffs") or []:
			if row.milestone == AES_DEADLINE:
				frappe.throw(
					_("Row {0}: {1} only applies when the destination country is the United States.").format(
						row.idx, frappe.bold(_(AES_DEADLINE))
					),
					title=_("Cut-offs"),
				)

	def set_cutoff_status(self):
		for row in self.get("cutoffs") or []:
			row.cutoff_status = get_cutoff_status(row.latest)

	def sync_container_rows(self):
		"""Carry the job's containers into its Transportation tab.

		A container is added once it has a number, and rows are never removed
		here: a container can run several transport legs with different
		transporters. To drop a container, remove it from the Container tab.
		Cancelled jobs are left alone.

		Container clearance rows belong to the job's Custom Clearance (D5):
		on_update hands new containers to it (sync_clearance_containers).
		"""
		if self.docstatus == 2:
			return

		containers = job_containers(self)
		if not containers:
			return

		if cint(self.svc_transportation) or cstr(self.transport) == "1":
			have = {cstr(r.reference_no).strip().upper() for r in self.get("transport_container_legs") or []}
			for number, size_type in containers:
				if number.upper() not in have:
					self.append("transport_container_legs", {"reference_no": number, "status": "Pending"})
					have.add(number.upper())

	def sync_clearance_containers(self):
		"""Add the job's new containers to its Custom Clearance's Containers
		table, without saving the clearance (rows are inserted directly)."""
		if self.docstatus == 2:
			return
		containers = job_containers(self)
		if not containers:
			return
		for name in frappe.get_all("Custom Clearance", filters={"operations": self.name}, pluck="name"):
			clearance = frappe.get_doc("Custom Clearance", name)
			for row in add_clearance_containers(clearance, containers):
				row.db_insert()

	def set_cost_accounts(self):
		"""A cost row with an item and no account books to the item's default
		expense account for the job's company (R2-28)."""
		for row in self.get("cost_table") or []:
			if row.item and not row.account:
				row.account = default_expense_account(row.item, self.company)

	def set_billing_status(self):
		"""How far the job's submitted Sales Invoices have been paid.

		Kept current by the Sales Invoice and Payment Entry hooks in
		forwarding.job_events; worked out here as well so a save never leaves
		it stale.
		"""
		from forwarding.job_events import get_billing_status

		self.billing_status = "No Invoice" if self.is_new() else get_billing_status(self.name)

	def ensure_project(self):
		"""Give the job its Project, named after the job.

		Per-job accounting runs through Project: the site's Sales and Purchase
		Invoice client scripts set `project` to the job's name, and Payment Entry
		and Estimation vs Actual read it the same way. Only a desk client script
		used to create it, after save — so a job saved any other way (the app, an
		import, a script) had none, and every invoice raised from it failed with
		"Could not find Project".
		"""
		if self.project and frappe.db.exists("Project", self.project):
			return
		if not frappe.db.exists("Project", self.name):
			project = frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": self.name,
					"company": self.company,
					"customer": self.customer,
					"cost_center": self.cost_center,
				}
			)
			project.flags.ignore_permissions = True
			project.insert(set_name=self.name)
		self.db_set("project", self.name, update_modified=False)

	def on_update(self):
		self.ensure_project()
		self.sync_clearance_containers()
		fields_to_transfer = ['awb_number']
		fields_to_transfer_project = ['cost_center']
		if self.freight:
			for field in fields_to_transfer:
				local_field_value = self.get(field)
				frappe.db.set_value("Freight",self.freight,field,local_field_value)
				# frappe.db.sql("""UPDATE `tabFreight` SET %s=%s where name=%s""",(field,local_field_value,self.freight))
				# frappe.msgprint(_("Updated {0} in Frieght {1}".format(field,self.freight)))
		if self.custom_clearance_id:
			for field in fields_to_transfer:
				local_field_value = self.get(field)
				frappe.db.set_value("Custom Clearance",self.custom_clearance,field,local_field_value)
				# frappe.msgprint(_("Updated {0} in Frieght {1}".format(field,self.custom_clearance)))
		if self.project:
			for field in fields_to_transfer_project:
				local_field_value = self.get(field)
				frappe.db.set_value("Project",self.project,field,local_field_value)
				# frappe.msgprint(_("Updated {0} in Project {1}".format(field,self.project)))
		# else:
		# 	if(frappe.db.exists("Project",self.name)):
		# 		self.set('project',self.name)
		# 	else:
		# 		project = frappe.get_doc({
		# 					"doctype":"Project",
		# 					"name":self.name,
		# 					"operations":self.name,
		# 					"cost_center":self.cost_center,
		# 					"customer":self.customer
		# 				})
		# 		try:
		# 			project.insert()
		# 			self.set('project',project.name)
		# 		except Exception as e:
		# 			frappe.log_error(message=e,title="Error creating project in operations")
				


# def _create_project(pr):
#     c = frappe.new_doc("Project")
#     c.project_name = pr.name
#     c.insert()
#     frappe.db.commit()
#     d = frappe.utils.get_link_to_form('Project', c.name)
#     frappe.msgprint(_("Projject {0} Created").format(d))
#     return c.name


# def create_project(doc,method):
#     pr = frappe.get_doc("Operations",doc.name)
#     if frappe.db.exists("Project", pr.name):
#         d = frappe.get_doc("Project",pr.name)
#         frappe.set_value("Project",pr.name,"name",d.name)
#         i.reload()
#         frappe.throw(_("Project {0} already exists").format(d))
#     else:
#         cd = _create_project_(pr)
#         frappe.db.set_value("Project", pr.name, "name", cd)
#         i.reload()
#         frappe.db.commit()
#         pr.reload()
@frappe.whitelist()
def make_freight(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
	
	def set_missing_values(source, target):
		pass

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Freight",
			"field_map": {

			}
		}
	}, target_doc, postprocess, ignore_permissions= ignore_permissions)

	return doclist

@frappe.whitelist()
def make_custom_clearance(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
	
	def set_missing_values(source, target):
		# A copied document is dated only once received (C16).
		undate_unreceived_documents(target)
		
	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Custom Clearance",
			# Clearance values a job still carries from before the clearance
			# owned them (D3); same-named fields map on their own.
			"field_map": {
				"bayan_no": "bayyan_number",
				"bayan_date": "bayyan_date",
				"do_no": "do_number",
			}
		},
		# Only the documents for the customs stage belong to the clearance.
		"Document Table": {
			"doctype": "Document Table",
			"condition": lambda row: cstr(row.stage).strip() == "Customs Clearance",
		},
		# Rows a job still carries from before the clearance owned them (D5).
		"Operations Clearance Container": {"doctype": "Operations Clearance Container"},
		"Operations Clearance Document": {"doctype": "Operations Clearance Document"},
	}, target_doc, postprocess, ignore_permissions= ignore_permissions)

	return doclist

@frappe.whitelist()
def make_transportaion(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
	
	def set_missing_values(source, target):
		# A copied document is dated only once received (C16).
		undate_unreceived_documents(target)
		
	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Transportation",
			"field_map": {

			}
		}
	}, target_doc, postprocess, ignore_permissions= ignore_permissions)

	return doclist
	
def _invoice_from_today(target):
	"""Undo what the job's same-named fields did to a mapped invoice.

	get_mapped_doc copies every field the two doctypes share. The job's
	`posting_date` landed on the invoice and the due date was worked out from
	it; saving then moved the posting date to today (posting time is not set)
	and left the due date behind it — "Due Date cannot be before Posting Date"
	on any job older than its credit days. The job's `naming_series` landed too,
	so invoices were numbered like jobs ("branch_abb-job_type_abb-…"). Both go
	back to the invoice's own defaults.
	"""
	target.posting_date = nowdate()
	target.due_date = None
	if target.meta.has_field("bill_date"):
		target.bill_date = None
	target.naming_series = None


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, ignore_permissions=False):
	# Only a submitted job is invoiced (R3-03); the invoice's validate says so too.
	from forwarding.invoice_guard import assert_job_submitted

	assert_job_submitted(source_name, "Sales Invoice")

	def postprocess(source, target):
		set_missing_values(source, target)
		#Get the advance paid Journal Entries in Sales Invoice Advance
		if target.get("allocate_advances_automatically"):
			target.set_advances()

	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = True
		_invoice_from_today(target)
		target.run_method("set_missing_values")
		target.run_method("set_po_nos")
		target.run_method("calculate_taxes_and_totals")

		if source.company_address:
			target.update({'company_address': source.company_address})
		else:
			# set company address
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Sales Invoice", 'company_address', target.company_address))

		# set the redeem loyalty points if provided via shopping cart
		# if source.loyalty_points and source.order_type == "Shopping Cart":
		# 	target.redeem_loyalty_points = 1

	def update_item(source, target, source_parent):
		target.amount = flt(source.rate)
		# target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = 1

		if source_parent.project:
			target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")
		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") \
				or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Sales Invoice",
			"field_map": {
				"name":"operations",
				"party_account_currency": "party_account_currency",
				"payment_terms_template": "payment_terms_template"
			},
			# "validation": {
			# 	"docstatus": ["=", 1]
			# }
		},
		"Cost Table": {
			"doctype": "Sales Invoice Item",
			"field_map": {
				"item": "item_code",
				"name":"cost_table"
			},
			"postprocess": update_item,
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"add_if_empty": True
		}
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist

@frappe.whitelist()
def make_purchase_invoice(source_name, target_doc=None, ignore_permissions=False):
	# Only a submitted job is invoiced (R3-03); the invoice's validate says so too.
	from forwarding.invoice_guard import assert_job_submitted

	assert_job_submitted(source_name, "Purchase Invoice")

	def postprocess(source, target):
		set_missing_values(source, target)
		#Get the advance paid Journal Entries in Purchase Invoice Advance
		if target.get("allocate_advances_automatically"):
			target.set_advances()

	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = True
		_invoice_from_today(target)
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

		if source.company_address:
			target.update({'company_address': source.company_address})
		else:
			# set company address
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Purchase Invoice", 'company_address', target.company_address))

		# set the redeem loyalty points if provided via shopping cart
		# if source.loyalty_points and source.order_type == "Shopping Cart":
		# 	target.redeem_loyalty_points = 1

	def update_item(source, target, source_parent):
		target.amount = flt(source.rate)
		# target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = 1

		if source_parent.project:
			target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")
		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") \
				or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Purchase Invoice",
			"field_map": {
				"name":"operations",
				"party_account_currency": "party_account_currency",
				"payment_terms_template": "payment_terms_template"
			},
			# "validation": {
			# 	"docstatus": ["=", 1]
			# }
		},
		"Cost Table": {
			"doctype": "Purchase Invoice Item",
			"field_map": {
				"item": "item_code",
				"name":"cost_table",
				"cost":"rate"
			},
			"postprocess": update_item,
		},
		"Purchase Taxes and Charges": {
			"doctype": "Purchase Taxes and Charges",
			"add_if_empty": True
		}
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist


@frappe.whitelist()
def make_booking(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)
		# #Get the advance paid Journal Entries in Purchase Invoice Advance
		# if target.get("allocate_advances_automatically"):
		# 	target.set_advances()

	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = True
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

		# if source.company_address:
		# 	target.update({'company_address': source.company_address})
		# else:
		# 	# set company address
		# 	target.update(get_company_address(target.company))

		# if target.company_address:
		# 	target.update(get_fetch_values("Purchase Invoice", 'company_address', target.company_address))

		# set the redeem loyalty points if provided via shopping cart
		# if source.loyalty_points and source.order_type == "Shopping Cart":
		# 	target.redeem_loyalty_points = 1

	def update_item(source, target, source_parent):
		# target.amount = flt(source.rate)
		# # target.base_amount = target.amount * flt(source_parent.conversion_rate)
		# target.qty = 1

		if source_parent.project:
			target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")
		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	doclist = get_mapped_doc("Operations", source_name, {
		"Operations": {
			"doctype": "Container Booking Request",
			"field_map": {
				# "name":"operations",
				# "party_account_currency": "party_account_currency",
				# "payment_terms_template": "payment_terms_template"
			}
			# "validation": {
			# 	"docstatus": ["=", 1]
			# }
		}
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist

	@frappe.whitelist()
	def make_delivery_note(source_name, target_doc=None, skip_item_mapping=False):
		def set_missing_values(source, target):
			target.ignore_pricing_rule = 1
			target.run_method("set_missing_values")
			target.run_method("set_po_nos")
			# target.run_method("calculate_taxes_and_totals")

			# if source.company_address:
			# 	target.update({'company_address': source.company_address})
			# else:
			# 	# set company address
			# 	target.update(get_company_address(target.company))

			# if target.company_address:
			# 	target.update(get_fetch_values("Delivery Note", 'company_address', target.company_address))

		def update_item(source, target, source_parent):
			# target.base_amount = (flt(source.qty)) * flt(source.base_rate)
			# target.amount = (flt(source.qty)) * flt(source.rate)
			target.qty = flt(source.qty) 
			target.pr_discount = flt(source.pr_discount) 
			target.po_rate = flt(source.rate) 

			item = get_item_defaults(target.item_code, source_parent.company)
			# item_group = get_item_group_defaults(target.item_code, source_parent.company)

			# if item:
			# 	target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center") \
			# 		or item.get("buying_cost_center") \
			# 		or item_group.get("buying_cost_center")

		mapper = {
			"Purchase Receipt": {
				"doctype": "Delivery Note",
				"validation": {
					"docstatus": ["=", 1]
				}
			}
		}

		if not skip_item_mapping:
			mapper["Purchase Receipt Item"] = {
				"doctype": "Delivery Note Item",
				"field_map": {
					"qty":"qty",
					"parent": "purchase_receipt_item",
				},
				"postprocess": update_item,
				# "condition": lambda doc: abs(doc.qty) < abs(doc.qty) and doc.delivered_by_supplier!=1
			}

		target_doc = get_mapped_doc("Purchase Receipt", source_name, mapper, target_doc, set_missing_values)

		return target_doc