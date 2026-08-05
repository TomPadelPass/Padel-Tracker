"""
Padel court utilisation tracker for Playtomic.

Runs on a schedule (GitHub Actions). Each run:
  1. Finds the club's tenant_id (cached in data/tenant.json after first run).
  2. Fetches availability for today + next 13 days from the public API.
  3. Upserts one row per (date, hour, court) into data/bookings.csv:
       status = "available" or "booked" (booked = not offered as bookable,
       which includes club-blocked hours - same as the grey cells on the site).
  4. Rows for hours that have already passed are never overwritten, so the
     last snapshot before each hour started becomes its final recorded state.

No authentication required - these are the same public endpoints the
Playtomic website uses.
"""

import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ---------------- configuration ----------------
CLUB_NAME_MATCH = "padel pass harpenden"   # case-insensitive substring
SEARCH_COORDINATE = "51.8175,-0.3524"      # Harpenden, used only for first-run lookup
SEARCH_RADIUS_M = 15000
LOCAL_TZ = ZoneInfo("Europe/London")
OPEN_HOUR = 8    # first bookable start hour shown on the grid
CLOSE_HOUR = 22  # courts close (last start hour is CLOSE_HOUR - 1)
DAYS_AHEAD = 14  # rolling window shown by the booking system
API = "https://api.playtomic.io/v1"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CSV_PATH = os.path.join(DATA_DIR, "bookings.csv")
TENANT_CACHE = os.path.join(DATA_DIR, "tenant.json")
# ------------------------------------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "X-Requested-With": "com.playtomic.web",
}


def get_json(path, params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def find_tenant():
    """Return (tenant_id, {resource_id: court_name}), cached after first run."""
    if os.path.exists(TENANT_CACHE):
        with open(TENANT_CACHE) as f:
            cached = json.load(f)
        return cached["tenant_id"], cached["resources"]

    tenants = get_json("/tenants", {
        "sport_id": "PADEL",
        "coordinate": SEARCH_COORDINATE,
        "radius": SEARCH_RADIUS_M,
    })
    tenant = next(
        (t for t in tenants
         if CLUB_NAME_MATCH in t.get("tenant_name", "").lower()),
        None,
    )
    if tenant is None:
        names = [t.get("tenant_name") for t in tenants]
        sys.exit(f"Club not found. Nearby clubs returned: {names}")

    resources = {
        r["resource_id"]: r.get("name", r["resource_id"])
        for r in tenant.get("resources", [])
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TENANT_CACHE, "w") as f:
        json.dump({"tenant_id": tenant["tenant_id"],
                   "tenant_name": tenant.get("tenant_name"),
                   "resources": resources}, f, indent=2)
    return tenant["tenant_id"], resources


def fetch_available_hours(tenant_id):
    """
    Return set of (date_str, hour, resource_id) that are bookable,
    in local (club) time. Playtomic API times are UTC.
    """
    now_local = datetime.now(LOCAL_TZ)
    start_min = now_local.strftime("%Y-%m-%dT00:00:00")
    start_max = (now_local + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%dT23:59:59")

    data = get_json("/availability", {
        "sport_id": "PADEL",
        "tenant_id": tenant_id,
        "start_min": start_min,
        "start_max": start_max,
    })

    available = set()
    for block in data:
        rid = block["resource_id"]
        day = block["start_date"]  # "YYYY-MM-DD" (UTC day)
        for slot in block.get("slots", []):
            t = slot["start_time"]  # "HH:MM:SS" UTC
            dt_utc = datetime.strptime(f"{day} {t}", "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc)
            duration = int(slot.get("duration", 60))
            # mark every full hour that this bookable slot could occupy
            local_start = dt_utc.astimezone(LOCAL_TZ)
            end = local_start + timedelta(minutes=duration)
            cur = local_start.replace(minute=0, second=0)
            while cur < end:
                available.add((cur.strftime("%Y-%m-%d"), cur.hour, rid))
                cur += timedelta(hours=1)
    return available


def load_csv():
    rows = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, newline="") as f:
            for r in csv.DictReader(f):
                rows[(r["date"], int(r["hour"]), r["court"])] = r
    return rows


def main():
    tenant_id, resources = find_tenant()
    available = fetch_available_hours(tenant_id)
    rows = load_csv()

    now_local = datetime.now(LOCAL_TZ)
    snapshot = now_local.strftime("%Y-%m-%d %H:%M")

    day = now_local.date()
    for d in range(DAYS_AHEAD):
        date = day + timedelta(days=d)
        date_s = date.isoformat()
        for hour in range(OPEN_HOUR, CLOSE_HOUR):
            hour_start = datetime(date.year, date.month, date.day, hour,
                                  tzinfo=LOCAL_TZ)
            if hour_start <= now_local:
                continue  # hour underway/past: keep last pre-hour snapshot
            for rid, court in resources.items():
                status = ("available" if (date_s, hour, rid) in available
                          else "booked")
                rows[(date_s, hour, court)] = {
                    "date": date_s,
                    "hour": hour,
                    "court": court,
                    "status": status,
                    "last_seen": snapshot,
                }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "hour", "court",
                                          "status", "last_seen"])
        w.writeheader()
        for key in sorted(rows, key=lambda k: (k[0], k[1], k[2])):
            w.writerow(rows[key])

    print(f"OK - {len(rows)} court-hours tracked, snapshot {snapshot}")


if __name__ == "__main__":
    main()
