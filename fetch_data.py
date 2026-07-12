#!/usr/bin/env python3
"""
Fetches temperature/wind/cloud forecasts from every available Open-Meteo model
(plus meteoblue, if an API key is set) for the four tracked airports, and
appends each run as a timestamped snapshot to data.json. Designed to run on
a schedule via GitHub Actions — see .github/workflows/update.yml.

No third-party packages required (stdlib only).
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta, timezone

STATIONS = [
    {"id": "warsaw",    "name": "Warsaw Chopin",        "lat": 52.1657, "lon": 20.9671},
    {"id": "madrid",    "name": "Madrid Adolfo Suárez",  "lat": 40.4839, "lon": -3.5680},
    {"id": "amsterdam", "name": "Amsterdam Schiphol",    "lat": 52.3086, "lon": 4.7639},
    {"id": "ankara",    "name": "Ankara Esenboğa",       "lat": 40.1281, "lon": 32.9951},
]

# Global / seamless models available at every station
MODELS = {
    "ecmwf_ifs025":           "ECMWF IFS",
    "ecmwf_aifs025_single":   "ECMWF AIFS (AI)",   # note: correct model string has "_single" suffix
    "gfs_seamless":           "GFS",
    "icon_seamless":          "ICON (global)",
    "icon_eu":                "ICON-EU",
    "meteofrance_arpege_europe": "ARPEGE (Europe)",  # what "meteofrance_seamless" actually resolves to
                                                       # outside France — kept explicit so it's not
                                                       # mistaken for the high-res AROME HD below
    "ukmo_seamless":          "UKMO",
    "gem_seamless":           "GEM (Canada)",
    "jma_seamless":           "JMA",
}

# Models only valid for specific stations (limited domain coverage)
RESTRICTED_MODELS = {
    "knmi_harmonie_arome_netherlands": {"name": "HARMONIE (KNMI)", "stations": {"amsterdam"}},
    # AROME HD's domain is mainland France + a modest margin beyond the border.
    # None of the 4 tracked airports are confidently inside that margin, but we
    # request it for all of them anyway — if a station is outside the domain,
    # Open-Meteo simply returns no data for it and it's silently skipped.
    "meteofrance_arome_france_hd": {"name": "AROME HD (France domain)", "stations": {"warsaw", "madrid", "amsterdam", "ankara"}},
}

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
METEOBLUE_KEY = os.environ.get("METEOBLUE_API_KEY", "").strip()


def http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "station-model-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_openmeteo_hourly(station, model_ids):
    params = {
        "latitude": station["lat"],
        "longitude": station["lon"],
        "hourly": "temperature_2m,wind_speed_10m,cloud_cover",
        "models": ",".join(model_ids),
        "forecast_days": 7,
        "timezone": "auto",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    try:
        return http_get_json(url)
    except Exception as e:
        print(f"  ! forecast fetch failed for {station['id']}: {e}", file=sys.stderr)
        return None


def fetch_openmeteo_actuals(station):
    today = date.today()
    start = today - timedelta(days=30)
    end = today - timedelta(days=1)
    params = {
        "latitude": station["lat"],
        "longitude": station["lon"],
        "daily": "temperature_2m_max",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "auto",
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
    try:
        return http_get_json(url)
    except Exception as e:
        print(f"  ! actuals fetch failed for {station['id']}: {e}", file=sys.stderr)
        return None


def fetch_meteoblue(station):
    if not METEOBLUE_KEY:
        return None
    # "basic-day" is the cheapest daily package — keeps us well inside the free 10M
    # credit/year allowance even fetching for all 4 airports every day.
    params = {
        "apikey": METEOBLUE_KEY,
        "lat": station["lat"],
        "lon": station["lon"],
        "format": "json",
    }
    url = "https://my.meteoblue.com/packages/basic-day?" + urllib.parse.urlencode(params)
    try:
        return http_get_json(url)
    except Exception as e:
        print(f"  ! meteoblue fetch failed for {station['id']}: {e}", file=sys.stderr)
        return None


def lead_days(target_date_str, today):
    target = date.fromisoformat(target_date_str)
    return (target - today).days


def append_snapshot(dataset, date_str, fields):
    # Always appends (doesn't overwrite same-day runs) so multiple runs per day
    # build real intraday history rather than erasing each other.
    arr = dataset.setdefault(date_str, [])
    arr.append({"capturedAt": datetime.now(timezone.utc).isoformat(), **fields})


def group_by_local_day(hourly):
    days = {}
    for i, ts in enumerate(hourly["time"]):
        d = ts[:10]
        days.setdefault(d, []).append(i)
    return days


def process_model(forecasts, model_id, hourly, today):
    temp_key = f"temperature_2m_{model_id}"
    wind_key = f"wind_speed_10m_{model_id}"
    cloud_key = f"cloud_cover_{model_id}"
    if temp_key not in hourly:
        print(f"    (no data for {model_id})")
        return
    days = group_by_local_day(hourly)
    dataset = forecasts.setdefault(model_id, {})
    for d, idxs in days.items():
        if lead_days(d, today) < 0:
            continue
        day_temps = [(i, hourly[temp_key][i]) for i in idxs if hourly[temp_key][i] is not None]
        if not day_temps:
            continue
        max_idx, max_val = max(day_temps, key=lambda t: t[1])
        fields = {"lead": lead_days(d, today), "temp": round(max_val, 1)}
        max_hour_str = hourly["time"][max_idx][11:16]  # "HH:MM" local time of the predicted max
        fields["maxHour"] = max_hour_str
        wind_arr = hourly.get(wind_key)
        cloud_arr = hourly.get(cloud_key)
        if wind_arr is not None and wind_arr[max_idx] is not None:
            fields["wind"] = round(wind_arr[max_idx], 1)
        if cloud_arr is not None and cloud_arr[max_idx] is not None:
            fields["cloud"] = round(cloud_arr[max_idx], 0)
        append_snapshot(dataset, d, fields)


def fetch_sunset(station):
    params = {
        "latitude": station["lat"],
        "longitude": station["lon"],
        "daily": "sunset",
        "forecast_days": 7,
        "timezone": "auto",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    try:
        resp = http_get_json(url)
        out = {}
        if resp and "daily" in resp:
            for d, s in zip(resp["daily"]["time"], resp["daily"]["sunset"]):
                if s:
                    out[d] = s[11:16]  # "HH:MM" local
        return out
    except Exception as e:
        print(f"  ! sunset fetch failed for {station['id']}: {e}", file=sys.stderr)
        return {}


def process_meteoblue(forecasts, mb_json, today):
    if not mb_json or "data_day" not in mb_json:
        return
    dd = mb_json["data_day"]
    times = dd.get("time", [])
    tmax = dd.get("temperature_max", [])
    dataset = forecasts.setdefault("meteoblue", {})
    for d, t in zip(times, tmax):
        if t is None or lead_days(d, today) < 0:
            continue
        append_snapshot(dataset, d, {"lead": lead_days(d, today), "temp": round(t, 1)})


def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
    else:
        data = {}

    today = date.today()

    for station in STATIONS:
        sid = station["id"]
        panel = data.setdefault(sid, {"forecasts": {}, "actuals": {}, "sunset": {}, "lastUpdated": None})
        panel.setdefault("sunset", {})

        model_ids = list(MODELS.keys())
        for rid, info in RESTRICTED_MODELS.items():
            if sid in info["stations"]:
                model_ids.append(rid)

        print(f"Fetching {station['name']} ({len(model_ids)} models)...")
        hourly_json = fetch_openmeteo_hourly(station, model_ids)
        if hourly_json and "hourly" in hourly_json:
            hourly = hourly_json["hourly"]
            for model_id in model_ids:
                process_model(panel["forecasts"], model_id, hourly, today)
        else:
            print(f"  ! no hourly forecast data returned for {sid}", file=sys.stderr)

        mb_json = fetch_meteoblue(station)
        if mb_json:
            process_meteoblue(panel["forecasts"], mb_json, today)

        actuals_json = fetch_openmeteo_actuals(station)
        if actuals_json and "daily" in actuals_json:
            for d, val in zip(actuals_json["daily"]["time"], actuals_json["daily"]["temperature_2m_max"]):
                if val is not None:
                    panel["actuals"][d] = round(val, 1)
        else:
            print(f"  ! no actuals returned for {sid}", file=sys.stderr)

        sunset_map = fetch_sunset(station)
        panel["sunset"].update(sunset_map)

        panel["lastUpdated"] = datetime.now(timezone.utc).isoformat()

    # model display-name lookup, written alongside the data so the dashboard
    # doesn't need its own hardcoded copy that could drift out of sync
    model_names = dict(MODELS)
    for rid, info in RESTRICTED_MODELS.items():
        model_names[rid] = info["name"]
    model_names["meteoblue"] = "meteoblue"
    data["_modelNames"] = model_names
    data["_stations"] = {s["id"]: {"name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in STATIONS}

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("Done.")


if __name__ == "__main__":
    main()
