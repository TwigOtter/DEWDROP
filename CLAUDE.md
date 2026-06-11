# CLAUDE.md

Guidance for Claude Code when working in the DEWDROP repo.

## What this is

DEWDROP ("Demonic Environmental Weather Detection, Reporting, and Observation
Project") is the **KC Weather Accuracy Tracker**. Each night it snapshots
forecasts from multiple free weather services for Kansas City (MCI), stores them
in SQLite, and — once the target day arrives — scores each service against
observed actuals. Signed per-service/per-horizon error builds bias curves that
power a bias-corrected, inverse-variance-weighted ensemble forecast.

The canonical spec is **`docs/kc_weather_tracker_design.md`**; the code conforms
to it. It runs on a headless Linux box. A read-only HTTP API serves both the
local-network web UI and (optionally, later) the **Berries** daemon — Berries
integration is not central; just don't break the HTTP query surface.

## Data model (design doc §3) — wide & daily

Three SQLite tables, one row per day per source:

- **`forecasts`** — `(service, fetched_on, target_date)` unique; carries
  `horizon_days`, `temp_high_f`, `temp_low_f`, `precip_mm`, `wind_max_mph`
  (max sustained wind), normalised `condition`, and `raw_json`. INSERT OR
  IGNORE = idempotent nightly snapshot.
- **`actuals`** — `(date, source)` unique; same metric columns. Multiple
  sources per date (`asos_mci` primary, `ecowitt_local` secondary).
- **`forecast_errors`** — one row per `(forecast_id, actuals_source)`; **signed**
  errors (predicted − actual, + = ran hot) + `condition_match`. Written **only**
  against the primary ground truth (`ENABLED_ACTUALS[0]` = `asos_mci`) and only
  for `horizon_days >= 0` — secondary actuals feed the microclimate offset,
  never the bias history.

## Architecture

- `dewdrop/` — `config.py` (all `.env` config), `models.py` (`ForecastDay`,
  `ActualDay`, condition vocab), `normalise.py` (condition mapping, §6),
  `db.py` (schema + helpers), `sources/` (one forecast service each),
  `actuals/` (`asos.py`, `ecowitt.py`), `scoring/score.py`, `blend/blender.py`
  (ensemble + bias curves), `api/main.py` (FastAPI), `web/static/` (the UI).
- `scripts/` — thin entrypoints for the systemd timers in `deploy/`.

## Conventions

- Config lives in `config.py`, loaded from `.env`; every module imports from it.
- Dates stored as ISO `YYYY-MM-DD`; timestamps as ISO-8601 UTC.
- Temps in °F, precip in **mm**. Every source maps its condition vocabulary
  onto `models.CONDITIONS` via `normalise` (`from_wmo_code` or `normalise_text`).
- New forecast source = subclass `sources.base.ForecastSource`, return one
  `ForecastDay` per target day, register in `sources/__init__.py:REGISTRY`.
  `open_meteo` is the reference implementation.
- New actuals source = add a `fetch(client, target_date) -> [ActualDay]` module
  under `actuals/` and register it in `actuals/__init__.py:REGISTRY`.
- systemd units are hardened (see any `deploy/*.service`); keep that block.

## Running

```bash
source venv/bin/activate
python scripts/init_db.py
python scripts/poll_forecasts.py          # snapshot forecasts (today..+10)
python scripts/ingest_actuals.py [DATE]   # fetch actuals (default: yesterday)
python scripts/run_scoring.py             # score forecasts that now have actuals
uvicorn dewdrop.api.main:app --port 8004  # API + web UI at /
```

Production: `deploy/setup.sh` installs to `/opt/dewdrop` and enables the timers
(`dewdrop-poll`, `dewdrop-actuals`, `dewdrop-score`) + `dewdrop-api.service`.

## Important

- **NWS** has no precip *amount* in its daily endpoint — `precip_mm` is null for
  it (high/low/condition are populated).
- **Keyed sources** (`openweathermap`, `tomorrow_io`, `weatherbit`) are stubs
  with the daily mapping documented; they raise until a key is set.
- **Wunderground**: free forecast API discontinued; stub with a caveat.
- **EcoWitt actuals** come from the *cloud history* API (daily high/low needs
  the time series), not the local live endpoint; skipped unless cloud creds set.
- **ASOS** endpoint/field names from IEM can drift — `actuals/asos.py` parses
  defensively. The ensemble needs ~90 days of history (§5) to be meaningful.
- **Schema changes**: added columns go in `db.SCHEMA` *and* `db._MIGRATIONS`
  (ALTER TABLE backfill); re-running `scripts/init_db.py` upgrades a live DB
  in place.
- **Ensemble guards** (§5.1): bias is only subtracted once a (service, horizon)
  has `MIN_BIAS_SAMPLES` (default 3) scored days, and non-negative metrics
  (precip, wind) are clamped at 0 after correction.
