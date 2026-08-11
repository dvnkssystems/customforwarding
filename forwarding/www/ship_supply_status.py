# Copyright (c) 2026, DVNKS Systems and contributors
"""Ship Supply — Delivery Status board (/ship-supply-status).

Full-screen kiosk web page. All values come from `build_ship_supply_board`
(shared with the desk page); nothing is static.
"""

import frappe
from forwarding.api import build_ship_supply_board

no_cache = 1


def get_context(context):
	context.no_cache = 1
	board = build_ship_supply_board()

	# Template indexes statuses by label (statuses[o.status]); the shared
	# builder returns an ordered list, so map it to a dict here.
	context.statuses = {s["label"]: s for s in board["statuses"]}
	context.orders = board["orders"]
	context.counters = board["counters"]
	context.pallet_summary = board["pallet_summary"]
	context.return_summary = board["return_summary"]
	return context
