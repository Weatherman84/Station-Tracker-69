#!/usr/bin/env python3
"""
Pulls the latest METAR observations (real airport reports, not model output)
from NOAA's free Aviation Weather Center Data API and appends them to
data.json under panel["metar"]. Meant to run frequently (e.g. every 30 min)
via .github/workflows/metar.yml, separate from the twice-daily model fetch —
this is your intraday "is reality tracking hot or cold" signal.

No API key needed. No third-party packages required (stdlib only).
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

STATIONS = [
    {"id": "warsaw",    "icao": "EPWA"},
    {"id": "madrid",    "icao": "LEMD"},
    {"id": "amsterdam", "icao": "EHAM"},
    {"id": "ankara",    "icao": "LTAC"},
]

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
KEEP_HOURS = 72  # trim METAR history older than this to keep the file small


def fetch_metar(icao):
    params = {"ids": icao, "format": "json", "hours": 3}
    url = "https://aviationweather.gov/api/data/metar?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "station-model-tracker/1.0 (contact: none)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ! METAR fetch failed for {icao}: {e}", file=sys.stderr)
        return None


def cloud_summary(report):
    # AWC's per-report "cover" (if present) reflects the dominant layer; otherwise
    # take the first entry in the "clouds" layer list. The field inside each layer
    # is called "cover" (e.g. "SCT", "BKN", "OVC", "CLR"), NOT "code".
    if report.get("cover"):
        return report["cover"]
    clouds = report.get("clouds")
    if clouds and isinstance(clouds, list) and len(clouds) > 0:
        return clouds[0].get("cover")
    return None


def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
    else:
        data = {}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=KEEP_HOURS)

    for station in STATIONS:
        sid = station["id"]
        panel = data.setdefault(sid, {"forecasts": {}, "actuals": {}, "metar": [], "lastUpdated": None})
        panel.setdefault("metar", [])

        print(f"Fetching METAR for {sid} ({station['icao']})...")
        reports = fetch_metar(station["icao"])
        if not reports:
            continue

        existing_obs_times = {m["obsTime"] for m in panel["metar"]}
        for r in reports:
            raw_obs_time = r.get("obsTime")  # AWC returns this as a Unix epoch integer (seconds)
            if raw_obs_time is None:
                continue
            try:
                obs_iso = datetime.fromtimestamp(int(raw_obs_time), tz=timezone.utc).isoformat()
            except Exception as e:
                print(f"  ! could not parse obsTime {raw_obs_time!r}: {e}", file=sys.stderr)
                continue
            if obs_iso in existing_obs_times:
                continue
            entry = {
                "obsTime": obs_iso,
                "temp": r.get("temp"),
                "dewp": r.get("dewp"),
                "wdir": r.get("wdir"),
                "wspd": r.get("wspd"),
                "wgst": r.get("wgst"),
                "cover": cloud_summary(r),
                "raw": r.get("rawOb"),
            }
            panel["metar"].append(entry)
            existing_obs_times.add(obs_iso)

        # trim old entries and keep sorted by time (obsTime is now always a clean ISO string)
        def parse_time(t):
            try:
                return datetime.fromisoformat(t)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        panel["metar"] = sorted(
            [m for m in panel["metar"] if parse_time(m["obsTime"]) >= cutoff],
            key=lambda m: m["obsTime"]
        )

        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)

    print("METAR update done.")


if __name__ == "__main__":
    main()
