#!/usr/bin/env python3
"""
One-time (re-runnable) backfill using Open-Meteo's Previous Runs API, which
stores what each model actually predicted at fixed lead times (1-7 days out)
going back to January 2024 for most models. This gives the tracker months of
lead-time-stratified history instantly instead of waiting for it to accumulate
day by day from the live fetch_data.py script.

Safe to re-run: backfilled entries are tagged "backfilled": true and keyed by
(date, lead), so re-running won't create duplicates — it'll just refresh them.

Trigger manually via the "Backfill history" GitHub Action (workflow_dispatch),
NOT on a schedule — this only needs to run once (or again later if you want to
extend the range).
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta, timezone

STATIONS = [
    {"id": "warsaw",    "name": "Warsaw Chopin",        "lat": 52.1657, "lon": 20.9671},
    {"id": "madrid",    "name": "Madrid Adolfo Suárez",  "lat": 40.4839, "lon": -3.5680},
    {"id": "amsterdam", "name": "Amsterdam Schiphol",    "lat": 52.3086, "lon": 4.7639},
    {"id": "ankara",    "name": "Ankara Esenboğa",       "lat": 40.1281, "lon": 32.9951},
]

MODELS = [
    "ecmwf_ifs025", "ecmwf_aifs025_single", "gfs_seamless", "icon_seamless", "icon_eu",
    "meteofrance_arpege_europe", "ukmo_seamless", "gem_seamless", "jma_seamless",
]
RESTRICTED_MODELS = {
    "knmi_harmonie_arome_netherlands": {"amsterdam"},
    "meteofrance_arome_france_hd": {"warsaw", "madrid", "amsterdam", "ankara"},
}

LEADS = [1, 2, 3, 4, 5, 6, 7]
BACKFILL_START = "2024-01-01"   # earliest most models are archived from
CHUNK_DAYS = 365                # split requests into ~1-year windows (fewer requests = faster)

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


def http_get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "station-model-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def date_chunks(start_str, end_str, chunk_days):
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        yield cur.isoformat(), chunk_end.isoformat()
        cur = chunk_end + timedelta(days=1)


def fetch_previous_runs(station, model_id, lead, start_str, end_str):
    params = {
        "latitude": station["lat"],
        "longitude": station["lon"],
        "hourly": f"temperature_2m_previous_day{lead},wind_speed_10m_previous_day{lead},cloud_cover_previous_day{lead}",
        "models": model_id,
        "start_date": start_str,
        "end_date": end_str,
        "timezone": "auto",
    }
    url = "https://previous-runs-api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    try:
        return http_get_json(url)
    except Exception as e:
        print(f"    ! {model_id} lead={lead} {start_str}..{end_str} failed: {e}", file=sys.stderr)
        return None


def group_by_local_day(hourly):
    days = {}
    for i, ts in enumerate(hourly["time"]):
        d = ts[:10]
        days.setdefault(d, []).append(i)
    return days


def upsert_backfill(dataset, date_str, lead, fields):
    arr = dataset.setdefault(date_str, [])
    for entry in arr:
        if entry.get("backfilled") and entry.get("lead") == lead:
            entry.update(fields)
            return
    fake_captured = (date.fromisoformat(date_str) - timedelta(days=lead)).isoformat() + "T06:00:00+00:00"
    arr.append({"capturedAt": fake_captured, "lead": lead, "backfilled": True, **fields})
    arr.sort(key=lambda e: e["capturedAt"])


def backfill_model(dataset, station, model_id, end_date_str):
    for lead in LEADS:
        for start_str, chunk_end_str in date_chunks(BACKFILL_START, end_date_str, CHUNK_DAYS):
            resp = fetch_previous_runs(station, model_id, lead, start_str, chunk_end_str)
            time.sleep(0.2)  # be polite to the free API
            if not resp or "hourly" not in resp:
                continue
            hourly = resp["hourly"]
            temp_key = f"temperature_2m_previous_day{lead}_{model_id}"
            wind_key = f"wind_speed_10m_previous_day{lead}_{model_id}"
            cloud_key = f"cloud_cover_previous_day{lead}_{model_id}"
            if temp_key not in hourly:
                # some providers/models don't support this lead — skip quietly
                continue
            days = group_by_local_day(hourly)
            for d, idxs in days.items():
                day_temps = [(i, hourly[temp_key][i]) for i in idxs if hourly[temp_key][i] is not None]
                if not day_temps:
                    continue
                max_idx, max_val = max(day_temps, key=lambda t: t[1])
                fields = {"temp": round(max_val, 1)}
                wind_arr = hourly.get(wind_key)
                cloud_arr = hourly.get(cloud_key)
                if wind_arr is not None and wind_arr[max_idx] is not None:
                    fields["wind"] = round(wind_arr[max_idx], 1)
                if cloud_arr is not None and cloud_arr[max_idx] is not None:
                    fields["cloud"] = round(cloud_arr[max_idx], 0)
                upsert_backfill(dataset, d, lead, fields)


def backfill_actuals(panel, station, end_date_str):
    for start_str, chunk_end_str in date_chunks(BACKFILL_START, end_date_str, 360):
        params = {
            "latitude": station["lat"], "longitude": station["lon"],
            "daily": "temperature_2m_max",
            "start_date": start_str, "end_date": chunk_end_str,
            "timezone": "auto",
        }
        url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
        try:
            resp = http_get_json(url)
        except Exception as e:
            print(f"    ! actuals {start_str}..{chunk_end_str} failed: {e}", file=sys.stderr)
            continue
        if resp and "daily" in resp:
            for d, val in zip(resp["daily"]["time"], resp["daily"]["temperature_2m_max"]):
                if val is not None:
                    panel["actuals"][d] = round(val, 1)
        time.sleep(0.2)


def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
    else:
        data = {}

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    only_station = os.environ.get("STATION_ID", "").strip()
    stations_to_run = [s for s in STATIONS if not only_station or s["id"] == only_station]
    if only_station and not stations_to_run:
        print(f"! STATION_ID={only_station!r} doesn't match any known station", file=sys.stderr)
        sys.exit(1)

    for station in stations_to_run:
        sid = station["id"]
        panel = data.setdefault(sid, {"forecasts": {}, "actuals": {}, "lastUpdated": None})

        model_ids = list(MODELS)
        for rid, allowed in RESTRICTED_MODELS.items():
            if sid in allowed:
                model_ids.append(rid)

        print(f"Backfilling {station['name']}...")
        for model_id in model_ids:
            print(f"  {model_id}")
            dataset = panel["forecasts"].setdefault(model_id, {})
            backfill_model(dataset, station, model_id, yesterday)

        print(f"  actuals")
        backfill_actuals(panel, station, yesterday)

        panel["lastUpdated"] = datetime.now(timezone.utc).isoformat()

        # save progress after each station — a long backfill that fails partway
        # through still keeps whatever it already fetched
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)

    print("Backfill done.")


if __name__ == "__main__":
    main()
