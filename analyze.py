"""Compute padel court utilisation from data/bookings.csv.

Only counts hours that have already happened (final state).
Usage: python analyze.py [YYYY-MM] (optional month filter)
"""

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/London")
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "bookings.csv")

month_filter = sys.argv[1] if len(sys.argv) > 1 else None
now = datetime.now(TZ)

total = defaultdict(lambda: [0, 0])       # court -> [booked, all]
by_hour = defaultdict(lambda: [0, 0])     # hour -> [booked, all]
by_weekday = defaultdict(lambda: [0, 0])  # weekday -> [booked, all]

with open(CSV_PATH, newline="") as f:
    for r in csv.DictReader(f):
        if month_filter and not r["date"].startswith(month_filter):
            continue
        dt = datetime(*map(int, r["date"].split("-")), int(r["hour"]), tzinfo=TZ)
        if dt >= now:
            continue  # hour not finished yet
        booked = 1 if r["status"] == "booked" else 0
        for bucket, key in ((total, r["court"]),
                            (by_hour, int(r["hour"])),
                            (by_weekday, dt.strftime("%a"))):
            bucket[key][0] += booked
            bucket[key][1] += 1

def pct(b, n):
    return f"{100 * b / n:5.1f}%  ({b}/{n})" if n else "  n/a"

print(f"Utilisation{' for ' + month_filter if month_filter else ''}\n")
print("By court:")
for court in sorted(total):
    b, n = total[court]
    print(f"  {court:<12}{pct(b, n)}")
b_all = sum(v[0] for v in total.values())
n_all = sum(v[1] for v in total.values())
print(f"  {'OVERALL':<12}{pct(b_all, n_all)}\n")

print("By hour of day:")
for h in sorted(by_hour):
    print(f"  {h:02d}:00  {pct(*by_hour[h])}")

print("\nBy weekday:")
for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
    if d in by_weekday:
        print(f"  {d}  {pct(*by_weekday[d])}")
