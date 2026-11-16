# Copyright (c) 2026, DVNKS Systems and contributors
"""Column totals for the Estimated Job reports, without pandas.

The reports used `pandas.DataFrame(rows).sum(numeric_only=True)`, and pandas
is not installed on every bench (freight.dvnks.com has none), so the reports
failed with "No module named 'pandas'". This does the same sum: per key, the
numbers in it; text, dates and blanks are skipped.
"""

from decimal import Decimal

NUMBER = (int, float, Decimal)


def sum_numeric(rows):
	"""{key: sum} over the numeric values of each key in `rows` (dicts)."""
	out = {}
	for row in rows or []:
		for key, value in dict(row).items():
			if isinstance(value, NUMBER) and not isinstance(value, bool):
				out[key] = out.get(key, 0) + float(value)
	return out
