# Station Model Tracker (automated)

Forecast-vs-actual backtesting dashboard for Polymarket max-temperature markets
on Warsaw Chopin, Madrid Adolfo Suárez, Amsterdam Schiphol, and Ankara Esenboğa.

Runs entirely on GitHub's free infrastructure — no server, no local machine
needing to stay awake, no Claude sandbox restrictions. A scheduled GitHub
Action fetches every available weather model twice a day and commits the
result as `data.json`; a static page (GitHub Pages) reads that file and
renders the dashboard.

## What it fetches

- **Open-Meteo** (free, no key): ECMWF IFS, ECMWF AIFS (AI model), GFS, ICON
  (global + EU), ARPEGE (Europe), UKMO, GEM, JMA — for all 4 airports — plus
  HARMONIE (KNMI) for Amsterdam only, and AROME HD requested for all 4 airports
  but realistically only likely to return data if a station falls inside its
  France-plus-border domain (none of the 4 confidently do — it's included so
  you can see for yourself rather than take our word for it). ARPEGE and
  AROME HD are listed as separate rows precisely so one doesn't get mistaken
  for the other. Wind speed and cloud cover are read at the exact hour each
  model predicts its own daily max, per model.
- **meteoblue** (optional, free tier, needs your own API key — see setup
  below): their blended daily forecast.
- **Live METAR** (free, no key, via NOAA's Aviation Weather Center): real
  hourly airport observations — temperature, dewpoint, wind, cloud cover —
  for EPWA (Warsaw), LEMD (Madrid), EHAM (Amsterdam), and LTAC (Ankara).
  Refreshed every ~30 minutes on its own schedule so you can see intraday
  whether the day is tracking hot or cold relative to what the models said,
  and react before the market resolves. Humidity is computed client-side
  from temp+dewpoint (Magnus formula) — no extra API call needed.
- **Polymarket prices** (free, no key, via the public Gamma API): best-effort
  automatic discovery of each airport's daily temperature market, refreshed
  every ~20 minutes. See the "Trading Mode" caveat below — this is genuinely
  best-effort keyword matching, not a guaranteed lookup.
- **Actuals** (daily max, for backtesting): Open-Meteo's reanalysis archive
  (a close proxy for the true station reading — you can manually override
  any date in the dashboard if you know the exact value Polymarket resolves
  against).

## Dashboard features

- **Model comparison**: all models side by side, with mean/median/spread and
  outlier flags (⚠ when a model is >1.5° from that day's median)
- **Auto bias-correction**: each model's raw forecast is automatically
  adjusted using its own historical bias at that lead time, plus a
  bias-corrected Consensus row
- **Live Nowcast**: instead of one number, a full probability distribution
  across 1° buckets for today, built from the bias-corrected consensus and
  historical error at this lead time
- **Surprise Index**: how often, historically, the actual value has landed
  completely outside every model's range
- **Confidence score + stars**: per-day, blending model spread, lead time,
  and historical accuracy
- **Trading Mode**: matched Polymarket bucket prices next to this tool's
  Nowcast probabilities, flagging possible value (🎯) where they diverge by
  more than 5 percentage points
- **Bet Tracker**: log your own bets (bucket, stake, price) and see
  resolved PnL/ROI/win-rate once the actual is known — **stored in your
  browser only** (localStorage), never written to data.json or committed to
  the repo, since GitHub Pages repos are public by default and this is your
  personal trading data

## One-time setup (10–15 minutes, no coding required)

### 1. Create a GitHub account
If you don't have one already: [github.com/join](https://github.com/join) (free).

### 2. Create a new repository
- Click the **+** in the top right → **New repository**
- Name it anything, e.g. `station-tracker`
- Set it to **Public** (required for free GitHub Pages) or Private if you
  have GitHub Pro — either works for Actions
- Click **Create repository**

### 3. Upload these files
In your new repo, click **Add file → Upload files**, and drag in everything
from this package **keeping the folder structure**, especially:
```
.github/workflows/update.yml     ← must stay in this exact path
.github/workflows/backfill.yml   ← must stay in this exact path
.github/workflows/metar.yml      ← must stay in this exact path
.github/workflows/polymarket.yml ← must stay in this exact path
fetch_data.py
backfill_history.py
metar_fetch.py
fetch_polymarket.py
index.html
data.json
README.md
```
Commit directly to the `main` branch.

### 4. (Optional) Add your meteoblue API key
Only needed if you want meteoblue included:
1. Sign up free at [meteoblue.com](https://www.meteoblue.com), activate the
   free Weather API for 1 year in your account overview
2. Copy your API key
3. In your repo: **Settings → Secrets and variables → Actions → New repository secret**
4. Name: `METEOBLUE_API_KEY`, value: your key
5. Save

If you skip this, everything still works — meteoblue is simply omitted.

### 5. Enable GitHub Pages
- **Settings → Pages**
- Under "Build and deployment", set **Source: Deploy from a branch**
- Branch: `main`, folder: `/ (root)` → **Save**
- After a minute or two, GitHub shows you the URL — something like
  `https://yourusername.github.io/station-tracker/`

### 6. Run the fetch once manually (don't wait for the schedule)
- Go to the **Actions** tab in your repo
- Click **"Update forecast data"** in the left sidebar
- Click **"Run workflow"** → **Run workflow** (green button)
- Wait ~30 seconds, refresh — you should see a green checkmark and a new
  commit updating `data.json`

### 6b. (Recommended) Backfill ~2.5 years of history in one go
Instead of waiting weeks for the leaderboard to become meaningful, run the
one-time backfill: it pulls Open-Meteo's **Previous Runs API**, which stores
exactly what each model predicted at 1–7 days lead time, going back to
January 2024 for most models.

- **Actions tab → "Backfill history"** (left sidebar) → **Run workflow**
- This runs as 4 separate jobs, one per airport, one after another (not in
  parallel) — each has its own 90-minute budget and commits its own progress
  as soon as it finishes, so a slow or failed station doesn't wipe out the
  others. Expect the whole thing to take roughly 30–60 minutes total.
- Safe to re-run any time (e.g. months later) to extend/refresh the range —
  it won't duplicate what's already there.
- If a station's job still times out, just re-run the workflow — Previous
  Runs API calls for a station that's already fully backfilled are fast, so
  a second pass mostly just needs to catch up whatever's missing.

### 6c. Start the live METAR feed
- **Actions tab → "Update METAR"** (left sidebar) → **Run workflow**
- This one is quick (a few seconds) — refresh after ~10 seconds and you
  should see a new commit
- From here it runs automatically every ~30 minutes on its own; no need to
  trigger it manually again

### 6d. Start the Polymarket price feed
- **Actions tab → "Update Polymarket"** (left sidebar) → **Run workflow**
- Check the log output — it prints exactly which market it matched (or
  didn't) for each airport. **This is best-effort keyword matching against
  Polymarket's public Gamma API**, not a guaranteed lookup — Polymarket
  doesn't publish a fixed slug pattern for these daily city markets. If a
  match looks wrong or is missing for a station, copy what the log printed
  and share it — the matching logic can be refined from real output.
- From here it runs automatically every ~20 minutes

### 7. Open your dashboard
Visit the Pages URL from step 5. You should see live data. From here on it
updates itself automatically twice a day (06:00 and 15:00 UTC) — nothing
more to do.

## Adjusting the schedule
Edit `.github/workflows/update.yml`, the `cron` line. Cron time is always
UTC. For example, `'0 5,12,18 * * *'` would run three times a day instead
of two.

## Notes
- The Action needs a few days to build up history before the leaderboard,
  MAE-by-lead, and confidence scores become meaningful — that's normal.
- If a run fails (e.g. Open-Meteo has a hiccup), check the Actions tab for
  the error log; it won't overwrite good data with a failed run.
- Actual-value overrides you enter in the dashboard are stored in your
  browser only (not synced across devices) — that part is intentionally
  local since it's a correction you make personally, not shared data.
