#!/usr/bin/env python3
"""
Best-effort automated discovery of today's Polymarket "highest temperature"
market for each tracked airport, via Polymarket's free public Gamma API
(no key, no wallet needed for reads).

IMPORTANT CAVEAT: Polymarket doesn't publish a fixed, guaranteed slug pattern
for these daily city-temperature markets, and the Gamma API's /events endpoint
doesn't support reliable free-text search. This script works around that by:
  1. Pulling the "weather" tag's events (or, if that tag isn't found, falling
     back to scanning all active events — slower, but still automatic)
  2. Filtering by city keyword + "temperature" in the title
  3. Preferring the event whose end date is today (or tomorrow, if a market
     for today isn't open yet) — since these are daily markets

This is inherently a bit fragile since it depends on Polymarket's exact
naming conventions matching what we guess. Check the Action log after the
first run: it prints exactly what it matched (or didn't) for each airport,
so you can see immediately whether the keyword list needs adjusting.

Writes into data.json under panel["market"] = {
  fetchedAt, eventSlug, question, buckets: [{label, price}, ...]
}
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timezone

STATIONS = [
    {"id": "warsaw",    "keywords": ["warsaw"]},
    {"id": "madrid",    "keywords": ["madrid"]},
    {"id": "amsterdam", "keywords": ["amsterdam"]},
    {"id": "ankara",    "keywords": ["ankara"]},
]

GAMMA_BASE = "https://gamma-api.polymarket.com"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


def http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "station-model-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def find_weather_tag_id():
    try:
        tags = http_get_json(f"{GAMMA_BASE}/tags?limit=200")
    except Exception as e:
        print(f"  ! could not fetch tags: {e}", file=sys.stderr)
        return None
    for t in tags:
        slug = (t.get("slug") or "").lower()
        name = (t.get("label") or t.get("name") or "").lower()
        if "weather" in slug or "weather" in name:
            return t.get("id")
    return None


def fetch_candidate_events(tag_id):
    events = []
    if tag_id:
        try:
            events = http_get_json(
                f"{GAMMA_BASE}/events?" + urllib.parse.urlencode({
                    "tag_id": tag_id, "active": "true", "closed": "false", "limit": 200
                })
            )
        except Exception as e:
            print(f"  ! could not fetch weather-tag events: {e}", file=sys.stderr)
    if not events:
        # Fallback: no weather tag found (or it returned nothing) — scan all
        # active events instead. Slower and noisier, but still fully automatic.
        print("  (falling back to scanning all active events — no weather tag matched)")
        try:
            events = http_get_json(
                f"{GAMMA_BASE}/events?" + urllib.parse.urlencode({
                    "active": "true", "closed": "false", "limit": 500,
                    "order": "volume24hr", "ascending": "false"
                })
            )
        except Exception as e:
            print(f"  ! could not fetch fallback events: {e}", file=sys.stderr)
            return []
    return events


def score_event(event, keywords):
    title = (event.get("title") or "").lower()
    if not any(k in title for k in keywords):
        return -1
    if "temperature" not in title and "high" not in title and "°" not in title:
        return -1
    score = 10
    end_date_str = event.get("endDate", "")
    if end_date_str:
        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00")).date()
            days_out = (end_date - date.today()).days
            if days_out == 0:
                score += 20
            elif days_out == 1:
                score += 10
            elif days_out < 0:
                score -= 50  # already resolved/past, skip preference
        except Exception:
            pass
    return score


def extract_buckets(event):
    buckets = []
    for m in event.get("markets", []):
        question = m.get("groupItemTitle") or m.get("question") or ""
        try:
            outcomes = json.loads(m.get("outcomes", "[]"))
            prices = json.loads(m.get("outcomePrices", "[]"))
        except Exception:
            continue
        # binary Yes/No market per bucket — take the "Yes" price as that bucket's probability
        if len(outcomes) >= 1 and len(prices) >= 1:
            try:
                yes_idx = outcomes.index("Yes") if "Yes" in outcomes else 0
                price = float(prices[yes_idx])
                label = question.strip() or m.get("question", "").strip()
                if label:
                    buckets.append({"label": label, "price": price})
            except Exception:
                continue
    return buckets


def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
    else:
        data = {}

    tag_id = find_weather_tag_id()
    print(f"weather tag_id: {tag_id}")
    events = fetch_candidate_events(tag_id)
    print(f"scanning {len(events)} candidate events")

    for station in STATIONS:
        sid = station["id"]
        panel = data.setdefault(sid, {"forecasts": {}, "actuals": {}, "lastUpdated": None})

        best_event, best_score = None, -1
        for ev in events:
            s = score_event(ev, station["keywords"])
            if s > best_score:
                best_score, best_event = s, ev

        if not best_event or best_score < 0:
            print(f"  {sid}: no matching market found")
            continue

        buckets = extract_buckets(best_event)
        if not buckets:
            print(f"  {sid}: matched '{best_event.get('title')}' but couldn't parse any buckets")
            continue

        panel["market"] = {
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "eventSlug": best_event.get("slug"),
            "question": best_event.get("title"),
            "buckets": buckets,
        }
        print(f"  {sid}: matched '{best_event.get('title')}' ({len(buckets)} buckets)")

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("Polymarket update done.")


if __name__ == "__main__":
    main()
