# Copyright (c) 2021, FirstERP and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from forwarding.carriers import on_carrier_change


class Carrier(Document):
	def on_update(self):
		on_carrier_change(self)

	def on_trash(self):
		on_carrier_change(self, deleted=True)
