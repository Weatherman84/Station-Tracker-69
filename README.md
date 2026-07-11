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
  (global + EU), ARPEGE/AROME, UKMO, GEM, JMA — for all 4 airports — plus
  HARMONIE (KNMI) for Amsterdam only (its domain doesn't cover the others).
  Wind speed and cloud cover are read at the exact hour each model predicts
  its own daily max, per model.
- **meteoblue** (optional, free tier, needs your own API key — see setup
  below): their blended daily forecast.
- **Live METAR** (free, no key, via NOAA's Aviation Weather Center): real
  hourly airport observations — temperature, dewpoint, wind, cloud cover —
  for EPWA (Warsaw), LEMD (Madrid), EHAM (Amsterdam), and LTAC (Ankara).
  Refreshed every ~30 minutes on its own schedule so you can see intraday
  whether the day is tracking hot or cold relative to what the models said,
  and react before the market resolves.
- **Actuals** (daily max, for backtesting): Open-Meteo's reanalysis archive
  (a close proxy for the true station reading — you can manually override
  any date in the dashboard if you know the exact value Polymarket resolves
  against).

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
.github/workflows/update.yml    ← must stay in this exact path
.github/workflows/backfill.yml  ← must stay in this exact path
.github/workflows/metar.yml     ← must stay in this exact path
fetch_data.py
backfill_history.py
metar_fetch.py
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
- This takes much longer than the daily fetch (potentially 20–40 minutes,
  since it pulls hourly data across ~10 models × 7 lead times × 4 airports)
  — that's normal, just let it run
- It saves progress after each airport, so if it times out partway through
  you can just run it again; already-backfilled data won't be duplicated
- Safe to re-run any time (e.g. months later) to extend/refresh the range

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
