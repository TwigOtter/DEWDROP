"""Central config, loaded from .env. Every module imports from here."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Project root = parent of this package dir.
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else val


# ── Storage ──────────────────────────────────────────────────────────────
DB_PATH = Path(_get("DEWDROP_DB_PATH", str(ROOT / "data" / "dewdrop.sqlite3")))

# ── Location being forecast (Kansas City by default) ─────────────────────
# Defaults to Kansas City Intl (MCI), the spec's reference location.
LOCATION_NAME = _get("DEWDROP_LOCATION_NAME", "kansas_city")
LATITUDE = float(_get("DEWDROP_LATITUDE", "39.2976"))     # MCI
LONGITUDE = float(_get("DEWDROP_LONGITUDE", "-94.7139"))  # MCI
TIMEZONE = _get("DEWDROP_TIMEZONE", "America/Chicago")

# How many days out to snapshot, today (horizon 0) through +HORIZON_DAYS.
HORIZON_DAYS = int(_get("DEWDROP_HORIZON_DAYS", "10"))

# Minimum scored days per (service, horizon) before the ensemble trusts the
# learned bias enough to subtract it. Below this, forecasts are blended
# uncorrected — a bias estimated from 1-2 days is mostly noise.
MIN_BIAS_SAMPLES = int(_get("DEWDROP_MIN_BIAS_SAMPLES", "3"))

# A day counts as "rain" at/above this much precip (mm). 0.25 mm ≈ the 0.01 in
# trace threshold ASOS reports at. Drives categorical precip scoring
# (rain/no-rain hits) and the ensemble's chance-of-rain vote.
RAIN_THRESHOLD_MM = float(_get("DEWDROP_RAIN_THRESHOLD_MM", "0.25"))

# ── Nightly DB backup (scripts/backup_db.py, dewdrop-backup.timer) ────────
BACKUP_DIR = Path(_get("DEWDROP_BACKUP_DIR", str(ROOT / "data" / "backups")))
BACKUP_KEEP = int(_get("DEWDROP_BACKUP_KEEP", "14"))  # newest N kept

# ── Actuals: NOAA ASOS / Iowa State Mesonet (primary ground truth) ───────
ASOS_STATION = _get("DEWDROP_ASOS_STATION", "MCI")
ASOS_NETWORK = _get("DEWDROP_ASOS_NETWORK", "MO_ASOS")    # MCI is in Missouri

# ── Actuals: EcoWitt GW2000 (apartment microclimate, secondary) ──────────
GW2000_HOST = _get("DEWDROP_GW2000_HOST", "")             # local LAN, e.g. 192.168.1.50
# Ecowitt cloud history API (gives daily max/min/precip); optional.
ECOWITT_APP_KEY = _get("ECOWITT_APP_KEY", "")
ECOWITT_API_KEY = _get("ECOWITT_API_KEY", "")
ECOWITT_MAC = _get("ECOWITT_MAC", "")

# Which actuals sources to ingest (comma-separated). ASOS is primary.
ENABLED_ACTUALS = [
    s.strip()
    for s in _get("DEWDROP_ENABLED_ACTUALS", "asos_mci").split(",")
    if s.strip()
]

# ── Forecast source API keys (keyless sources ignore these) ──────────────
OPENWEATHERMAP_API_KEY = _get("OPENWEATHERMAP_API_KEY", "")
TOMORROW_IO_API_KEY = _get("TOMORROW_IO_API_KEY", "")
WEATHERBIT_API_KEY = _get("WEATHERBIT_API_KEY", "")
WUNDERGROUND_API_KEY = _get("WUNDERGROUND_API_KEY", "")   # see README caveat

# Which forecast sources are enabled (comma-separated). Default: the keyless
# ones, so the pipeline runs end-to-end before you've signed up for anything.
ENABLED_SOURCES = [
    s.strip()
    for s in _get("DEWDROP_ENABLED_SOURCES", "open_meteo,nws").split(",")
    if s.strip()
]

# ── Read-only HTTP API (web UI + Berries) ────────────────────────────────
API_HOST = _get("DEWDROP_API_HOST", "127.0.0.1")
API_PORT = int(_get("DEWDROP_API_PORT", "8004"))


# ── Local time ───────────────────────────────────────────────────────────
# The server runs in UTC, but all weather is reasoned about in the location's
# local calendar day (TIMEZONE). Anything that asks "what day is it" — forecast
# snapshot dates, horizons, "yesterday" for actuals, day-window cutoffs — MUST
# go through these so it doesn't roll over at 00:00 UTC (e.g. 7pm CDT). Pure
# *timestamps* (an instant in time) should stay UTC; these are for calendar days.
def tz() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def local_now() -> datetime:
    """Timezone-aware 'now' in the configured local timezone."""
    return datetime.now(ZoneInfo(TIMEZONE))


def local_today() -> date:
    """Today's date on the local calendar (not the server's UTC date)."""
    return local_now().date()
