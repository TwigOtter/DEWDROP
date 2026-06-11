# KC Weather Accuracy Tracker
### Design Document — v0.1

**Project goal:** Continuously snapshot forecasts from multiple free weather services for the Kansas City area, score each service against observed actuals, and build per-service bias models that power a bias-corrected ensemble forecast over time.

**Platform:** ottserver0 (headless Linux) · Python · SQLite · Local-network web UI

---

## 1. Overview

Each night at midnight a cron job queries every configured weather API and stores a forecast snapshot for the current day through 10 days out. The horizon (days until the target date) is derived and stored alongside the raw predictions. When a target date arrives, actuals are fetched from NOAA's ASOS network (MCI station) and from the local Ecowitt GW2000 weather station. Error records are computed for every `(service, target_date, horizon)` tuple. Over time, per-service bias curves emerge and power a weighted ensemble forecast.

---

## 2. Data Sources

### 2.1 Forecast Services (free tier)

| Service | Key Required | Notes |
|---|---|---|
| NWS (`api.weather.gov`) | No | Official government data; also used as a competitor |
| Open-Meteo (`open-meteo.com`) | No | Exposes multiple underlying models (GFS, ECMWF, ICON) — treat as one service for now |
| OpenWeatherMap | Yes | Free tier; one of the most widely-used consumer APIs |
| Tomorrow.io | Yes | Free tier; interesting proprietary model |
| Weatherbit | Yes | Free tier; good 10-day forecast endpoint |

### 2.2 Actuals Sources

- **NOAA ASOS / Iowa State Mesonet — MCI station** as primary ground truth
- **Ecowitt GW2000 local station** — apartment-microclimate actuals from the balcony. The schema supports multiple actuals sources per date, so both run in parallel from day one.

---

## 3. Database Schema

SQLite database on ottserver0. Three primary tables; scores are computed on demand or materialised nightly.

### 3.1 `forecasts`

```sql
CREATE TABLE forecasts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT    NOT NULL,         -- e.g. 'nws', 'open_meteo', 'owm'
    fetched_on    DATE    NOT NULL,         -- date the snapshot was taken (UTC)
    target_date   DATE    NOT NULL,         -- the day being predicted
    horizon_days  INTEGER NOT NULL,         -- target_date - fetched_on (stored for query speed)
    temp_high_f   REAL,                     -- predicted high (°F)
    temp_low_f    REAL,                     -- predicted low (°F)
    precip_mm     REAL,                     -- predicted precipitation amount (mm)
    wind_max_mph  REAL,                     -- predicted max sustained wind (mph)
    condition     TEXT,                     -- normalised condition label (see §6)
    raw_json      TEXT,                     -- full API response blob for re-processing
    UNIQUE (service, fetched_on, target_date)
);
```

> Unique constraint on `(service, fetched_on, target_date)` prevents duplicate snapshots and makes the nightly run idempotent.

### 3.2 `actuals`

```sql
CREATE TABLE actuals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         DATE    NOT NULL,
    source       TEXT    NOT NULL,          -- e.g. 'asos_mci', 'ecowitt_local'
    temp_high_f  REAL,
    temp_low_f   REAL,
    precip_mm    REAL,
    wind_max_mph REAL,                      -- observed max sustained wind (mph)
    condition    TEXT,
    fetched_at   DATETIME NOT NULL
);
```

> Multiple rows per date are allowed — one for ASOS MCI, one for the Ecowitt station. This lets us eventually compare microclimate vs. airport actuals directly.

### 3.3 `forecast_errors`

```sql
CREATE TABLE forecast_errors (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id    INTEGER NOT NULL REFERENCES forecasts(id),
    service        TEXT    NOT NULL,        -- denormalised for simpler queries
    target_date    DATE    NOT NULL,        -- denormalised for simpler queries
    horizon_days   INTEGER NOT NULL,        -- denormalised for simpler queries
    actuals_source TEXT    NOT NULL,        -- which actuals row was used
    temp_high_err  REAL,                    -- predicted − actual (positive = ran hot)
    temp_low_err   REAL,                    -- predicted − actual (positive = ran hot)
    precip_err     REAL,                    -- predicted − actual (positive = over-forecast)
    wind_err       REAL,                    -- predicted − actual (positive = over-forecast)
    condition_match INTEGER                 -- 1 if condition matched, 0 if not
);
```

> Errors are **signed**: positive = over-predicted, negative = under-predicted. This is what enables bias detection rather than just accuracy measurement.

> Scoring is anchored on a **single ground-truth source** (`asos_mci`). Other actuals rows (e.g. the local station) are kept for the microclimate comparison but are not scored against, so they can't dilute the bias/variance history.

---

## 4. Nightly Run (cron @ midnight)

The main script runs in two phases. Both are idempotent — re-running on the same night is safe.

### Phase 1 — Snapshot Collection

1. For each configured service, query the forecast API for today through today+10.
2. Normalise each day's response into the `forecasts` schema fields.
3. Compute `horizon_days = target_date − today`.
4. `INSERT OR IGNORE` into `forecasts` (duplicate guard on unique constraint).
5. Store the raw JSON blob in `raw_json` for future re-parsing if the schema changes.

### Phase 2 — Scoring

1. Fetch actuals for yesterday from both ASOS MCI and Ecowitt GW2000. Insert into `actuals` if not already present.
2. Ground-truth rows with no condition label (ASOS daily summaries never carry one) get a coarse label **derived** from observed precip (rain / heavy_rain / snow by temperature) and — on dry days — the local station's peak solar reading vs. a rough clear-sky maximum (clear / partly_cloudy / cloudy). The derivation is written back to the actuals row.
3. Query all `forecasts` rows where `target_date = yesterday` AND no `forecast_errors` row exists yet (ground-truth source only, `horizon_days >= 0` only).
4. For each forecast row, compute signed errors vs. the actuals row, plus `precip_hit` — the **categorical** rain/no-rain call at the `RAIN_THRESHOLD_MM` cutoff (default 0.25 mm). Daily mm error is dominated by a few storm days; the hit rate is the better trust signal.
5. Insert the error records into `forecast_errors`.
6. Optionally materialise an aggregated bias view (mean error + std dev per service per horizon).

---

## 5. Ensemble Forecast Algorithm

Once enough error history has accumulated (~90 days minimum), the system can produce a bias-corrected ensemble forecast for any future date.

### 5.1 Bias Correction

For each service and horizon, compute the mean signed error from `forecast_errors`:

```
bias(service, horizon)     = AVG(temp_high_err)
                             WHERE service = ? AND horizon_days = ?

corrected_forecast         = raw_forecast − bias(service, horizon)
```

Three guards keep the correction physical and robust:

- The bias is only subtracted once a `(service, horizon)` has at least
  `MIN_BIAS_SAMPLES` scored days (default 3) — a bias estimated from one or
  two days is mostly noise.
- Non-negative quantities (precip, wind) are clamped at 0 after correction;
  a correction past zero just means "none".
- Error samples are **winsorized** (clipped to the 5th–95th percentile, once
  a `(service, horizon)` has ≥10 samples) before the bias/variance are
  computed, so one busted reading can't poison a curve for months.

The ensemble also reports a **chance of rain**: each service with a precip
number votes rain/no-rain at the threshold, weighted by its historical
rain/no-rain hit rate at that horizon (unproven services count as a coin
flip), and a **history_days** count — the weakest contributing service's
scored-day count — so the UI can show how much history backs each day's
correction.

### 5.2 Weighted Aggregation

Weight each bias-corrected forecast by the inverse of its historical variance at that horizon. Consistent services get more weight; noisy ones get less.

```
variance(service, horizon) = VARIANCE(temp_high_err)
                             WHERE service = ? AND horizon_days = ?

weight(service, horizon)   = 1.0 / variance(service, horizon)

ensemble_temp_high         = SUM(weight_i × corrected_i) / SUM(weight_i)
```

### 5.3 Uncertainty Band

Report the weighted standard deviation across services as the uncertainty interval — e.g. "71°F ± 4°F". Wider bands at longer horizons are expected and informative.

---

## 6. Condition Label Normalisation

Different APIs use wildly different condition vocabularies. Map everything to a small controlled set before storage:

| Normalised Label | Maps From |
|---|---|
| `clear` | sunny, clear sky, fair |
| `partly_cloudy` | partly cloudy, mostly sunny, scattered clouds |
| `cloudy` | cloudy, overcast, mostly cloudy |
| `rain` | rain, drizzle, showers, light rain, moderate rain |
| `heavy_rain` | heavy rain, thunderstorms, severe storms |
| `snow` | snow, flurries, sleet, wintry mix |
| `fog` | fog, mist, haze |

---

## 7. Frontend (Local Network Web UI)

A read-only webpage served by Flask. Accessible only on the local network. No authentication needed for v1.

### 7.1 Views

- **Dashboard** — today's ensemble forecast for the next 10 days with uncertainty bands. Quick summary of which services are currently most accurate at each horizon.
- **Service Comparison** — per-service accuracy table. Columns: service, mean temp high error, mean temp low error, mean precip error, condition accuracy %, data points collected. Filterable by horizon range and date range.
- **Bias Curves** — line chart: x-axis = horizon (0–10 days), y-axis = mean signed error per service. Shows whether a service runs systematically hot or cold and how far out its forecast degrades.
- **Daily Drill-down** — pick any past date, see what every service predicted at every horizon vs. what actually happened.
- **Raw Log** — scrollable table of recent `forecast_errors` rows. Mostly a debug view.

### 7.2 Tech Stack

- **Backend:** Flask (Python) serving JSON endpoints
- **Frontend:** Single HTML file with vanilla JS + Chart.js for bias curve charts. No build step, no framework — loads in any browser.
- **Data:** All queries hit SQLite directly via Flask. No caching layer needed at this scale.

---

## 8. Suggested File Layout

```
kc-weather/
  db/
    weather.db                  ← SQLite database
  collector/
    __init__.py
    fetch_nws.py
    fetch_open_meteo.py
    fetch_owm.py
    fetch_tomorrow.py
    fetch_weatherbit.py
    normalise.py                ← condition label mapping
  scorer/
    fetch_actuals_asos.py       ← pulls from NOAA ASOS MCI
    fetch_actuals_ecowitt.py    ← pulls from GW2000 local HTTP endpoint
    score.py                    ← computes & inserts forecast_errors
  ensemble/
    bias.py                     ← bias correction & weighting
    forecast.py                 ← ensemble output
  web/
    server.py                   ← Flask app
    static/
      index.html
      app.js
      style.css
  run_nightly.py                ← entry point called by cron
  schema.sql                    ← CREATE TABLE statements
  config.yaml                   ← API keys, station IDs, toggles
```

---

## 9. Phased Roadmap

| Phase | Name | Scope |
|---|---|---|
| 1 | Collection | Cron job + schema. Collect data from all free APIs. No scoring yet. |
| 2 | Local Station | Integrate Ecowitt GW2000 as actuals source from day one. |
| 3 | Scoring | Nightly actuals fetch from both ASOS MCI and Ecowitt. Compute & store `forecast_errors`. |
| 4 | Web UI | Flask server + dashboard + service comparison table + bias curves. |
| 5 | Ensemble | Bias correction + weighted ensemble forecast once ~90 days of data exist. |

---

*v0.1 — initial design · subject to revision as collection begins*
