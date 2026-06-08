# DEWDROP

**Demonic Environmental Weather Detection, Reporting, and Observation Project**
— the KC Weather Accuracy Tracker.

Each night DEWDROP snapshots forecasts from several free weather services for
Kansas City (MCI), stores them in SQLite, and — once each target day arrives —
scores every service against observed actuals (NOAA ASOS at MCI, plus an
optional EcoWitt **GW2000** microclimate reading). Signed per-service error
builds bias curves, which power a bias-corrected, inverse-variance-weighted
**ensemble** forecast. A local-network web UI visualises it all; the same
read-only HTTP API can also be queried by **Berries** later.

> Canonical spec: [`docs/kc_weather_tracker_design.md`](docs/kc_weather_tracker_design.md).
> Runs as its own `dewdrop` service user under `/opt/dewdrop`.

## Pipeline

```
   forecast services ──> poll_forecasts ──┐
   (NWS, Open-Meteo, ...)   nightly        │
                                           ▼
                                      forecasts ──┐
                                                  ├──> run_scoring ──> forecast_errors
   actuals (ASOS/MCI, EcoWitt) ──> ingest_actuals ┘     nightly            │
              nightly, for yesterday                                       ▼
                                          blend.blender ──> bias-corrected ensemble
                                                                           │
                          web UI + Berries  <── dewdrop.api (port 8003) ───┘
```

## Data model (3 wide, daily tables)

| Table | Grain | Key columns |
|-------|-------|-------------|
| `forecasts` | one service's prediction for one target day | `service, fetched_on, target_date, horizon_days, temp_high_f, temp_low_f, precip_mm, condition, raw_json` |
| `actuals` | observed weather for one day from one source | `date, source, temp_high_f, temp_low_f, precip_mm, condition` |
| `forecast_errors` | signed error per forecast × actuals source | `temp_high_err, temp_low_err, precip_err, condition_match` |

Temps °F, precip mm, conditions normalised to a controlled set (see
`dewdrop/normalise.py`). Errors are signed (predicted − actual; + = ran hot).

## Layout

| Path | What |
|------|------|
| `dewdrop/config.py` | All config from `.env` (KC/MCI defaults) |
| `dewdrop/db.py` | SQLite schema + helpers (3 tables above) |
| `dewdrop/models.py` | `ForecastDay`, `ActualDay`, condition vocabulary |
| `dewdrop/normalise.py` | Condition normalisation (text + WMO codes) |
| `dewdrop/sources/` | One module per forecast service; `open_meteo.py` is the reference |
| `dewdrop/actuals/` | `asos.py` (primary ground truth), `ecowitt.py` (secondary) |
| `dewdrop/scoring/score.py` | Nightly signed-error scoring |
| `dewdrop/blend/blender.py` | Bias correction + inverse-variance ensemble + bias curves |
| `dewdrop/api/main.py` | FastAPI: JSON endpoints + serves the web UI |
| `dewdrop/web/static/` | Single-page Chart.js UI (no build step) |
| `scripts/`, `deploy/` | Timer entrypoints; systemd units + `setup.sh` |

## Install (on the Linux box)

```bash
sudo bash /home/twig/dewdrop/deploy/setup.sh   # one privileged step
sudoedit /opt/dewdrop/.env                      # coords, ASOS station, keys
sudo systemctl restart dewdrop-api
systemctl list-timers 'dewdrop-*'
```

## Local dev / smoke test (no sudo)

```bash
cd /home/twig/dewdrop
python3 -m venv venv && source venv/bin/activate
pip install -e .
python scripts/init_db.py
python scripts/poll_forecasts.py        # keyless open_meteo + nws by default
python scripts/ingest_actuals.py        # yesterday's ASOS/MCI actuals
python scripts/run_scoring.py
uvicorn dewdrop.api.main:app --port 8003   # open http://localhost:8003/
pytest -q
```

## Web UI / API (port 8003)

`/` serves the dashboard. JSON endpoints (also Berries-queryable):

- `GET /api/ensemble` (alias `GET /forecast`) — bias-corrected ensemble, next 10 days
- `GET /api/services` — per-service accuracy table (filters: `horizon_min/max`, `date_from/to`)
- `GET /api/bias-curves?metric=temp_high_err` — mean signed error by horizon
- `GET /api/daily/{YYYY-MM-DD}` — every service at every horizon vs. the actual
- `GET /api/errors?limit=200` — raw `forecast_errors` log

## Sources & keys

| Source | Key | Status |
|--------|-----|--------|
| `open_meteo` | no | **implemented** (reference, daily endpoint) |
| `nws` | no | **implemented** (high/low/condition; no precip amount) |
| `openweathermap` | yes | stub (daily mapping documented) |
| `tomorrow_io` | yes | stub |
| `weatherbit` | yes | stub |
| `wunderground` | yes | **stub + caveat** (free forecast API discontinued) |

| Actuals source | Key | Status |
|----------------|-----|--------|
| `asos_mci` | no | **implemented** — NOAA ASOS via Iowa Mesonet (primary) |
| `ecowitt_local` | cloud creds | **implemented** — EcoWitt cloud history (skipped if unset) |

## Status

Conforms to the v0.1 design doc through Phase 5 scaffolding: collection,
actuals, scoring, ensemble, and web UI are wired end-to-end. The ensemble needs
~90 days of accumulated error history (§5) before its bias correction is
meaningful. Keyed forecast sources remain stubs pending API keys.
