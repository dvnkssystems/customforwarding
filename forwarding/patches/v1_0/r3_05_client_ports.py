# Copyright (c) 2026, DVNKS Systems and contributors
"""Port fixes for Royal Eagle's own data (R3-05 retest, 29 Oct).

On 27 Oct the old server's ports were corrected by hand: foreign ports
tagged Saudi Arabia got their real country, and duplicates were merged.
The client's data (the new server) came without those edits, so Simran saw
Busan, Chittagong, Laem Chabang, Nanjin and Jabel Ali as Saudi Arabia again.
This repeats the same fixes as a patch:

- COUNTRIES: the country each port has on the old server.
- 0-BUSAN is merged into KRPUS-Busan, and DAM PORT-DAMMAM PORT and
  DM-DAMMAM into SADMM-Ad Dammam (created as on the old server when
  missing); a merge repoints every job using the port.

Each step is skipped when its records are missing, so the patch runs on any
site; running it again changes nothing.
"""

import frappe
from frappe.model.rename_doc import rename_doc

COUNTRIES = {
	"002-COCHIN": "India",
	"BHR-BAHRAIN": "Bahrain",
	"CCJ-CALICUT": "India",
	"CNTSN-TIANJIN SEA": "China",
	"CTG-CHITTAGONG": "Bangladesh",
	"HEA-HEATHROW": "United Kingdom",
	"HGW-HONGWAN": "China",
	"JAWAHARLAL NEHRU PORT, INDIA": "India",
	"JEA-JABEL ALI": "United Arab Emirates",
	"KWT-KUWAIT": "Kuwait",
	"LMCH-LAEM CHABANG": "Thailand",
	"NANJIN-NANJIN": "China",
	"PPV-PIPAVAV": "India",
	"TKY-JP-TOKYO": "Japan",
	"TMA-TEMA": "Ghana",
	"port_code-ATLANTA": "United States",
	"port_code-BELGRADE AIR PORT": "Serbia and Montenegro",
	"port_code-BUD": "Hungary",
	"port_code-BUDAPEST": "Hungary",
	"port_code-BUSAN PORT": "Korea, Republic of",
	"port_code-CALICUT": "India",
	"port_code-COCHIN, COK": "India",
	"port_code-COCHIN, INDIA": "India",
	"port_code-DOUALA": "Cameroon",
	"port_code-DOUALA,": "Cameroon",
	"port_code-Dubai": "United Arab Emirates",
	"port_code-EVOSMOS": "Greece",
	"port_code-EVYAP PORT": "Turkey",
	"port_code-EVYAP PORT/ KOCAELI": "Turkey",
	"port_code-GAEVLE PORT": "Sweden",
	"port_code-GENEVE": "Switzerland",
	"port_code-Guangzhou": "China",
	"port_code-HONGWAN": "China",
	"port_code-ICD ,KANPUR TO NHAVA SHEVA": "India",
	"port_code-ICN-INCHEON": "Korea, Republic of",
	"port_code-INCHEON": "Korea, Republic of",
	"port_code-INDONESA": "Indonesia",
	"port_code-JAWAHARLAL NEHRU": "India",
	"port_code-JAWAHARLAL NEHRU PORT, INDIA": "India",
	"port_code-KARACHI PORT": "PAKISTAN",
	"port_code-LAEM CHABANG, THAILAND": "Thailand",
	"port_code-MAASTRICHT": "Netherlands",
	"port_code-QINGDAO CHINA": "China",
	"port_code-RAS AL KHAIMAH": "United Arab Emirates",
	"port_code-SCHIPHOL": "Netherlands",
	"port_code-TIANJIN SEA": "China",
	"port_code-coc": "India",
	"port_code-hongwan , china": "China",
	"port_code-hongwan ,china": "China",
}

DAMMAM = {"port_code": "SADMM", "port_name": "Ad Dammam", "country": "Saudi Arabia", "mode_of_shipment": "Sea"}

MERGES = [
	("0-BUSAN", "KRPUS-Busan"),
	("DAM PORT-DAMMAM PORT", "SADMM-Ad Dammam"),
	("DM-DAMMAM", "SADMM-Ad Dammam"),
]


def execute():
	for port, country in COUNTRIES.items():
		if frappe.db.exists("Port", port) and frappe.db.exists("Territory", country):
			frappe.db.set_value("Port", port, "country", country, update_modified=False)

	if not frappe.db.exists("Port", "SADMM-Ad Dammam") and frappe.db.exists("Territory", DAMMAM["country"]):
		frappe.get_doc({"doctype": "Port", **DAMMAM}).insert(ignore_permissions=True)

	for old, new in MERGES:
		if frappe.db.exists("Port", old) and frappe.db.exists("Port", new):
			rename_doc("Port", old, new, merge=True, force=True, show_alert=False)
