"""Shared data types and the canonical vocabularies.

The schema is the spec's **wide daily** model: one row per
(service, fetched_on, target_date) carrying that day's predicted high/low,
precip and a normalised condition label. Horizon (days until the target date)
is derived from the two dates.

Keeping the condition vocabulary in one place is what lets every source, the
actuals fetchers and the scorer speak the same language.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

# ── Normalised condition labels (design doc §6) ──────────────────────────
# Every source maps its provider vocabulary onto exactly one of these.
CLEAR = "clear"
PARTLY_CLOUDY = "partly_cloudy"
CLOUDY = "cloudy"
RAIN = "rain"
HEAVY_RAIN = "heavy_rain"
SNOW = "snow"
FOG = "fog"

CONDITIONS = (CLEAR, PARTLY_CLOUDY, CLOUDY, RAIN, HEAVY_RAIN, SNOW, FOG)


@dataclass(slots=True)
class ForecastDay:
    """One service's prediction for one target day, taken on one fetch date."""
    service: str
    fetched_on: date          # date the snapshot was taken (UTC)
    target_date: date         # the day being predicted
    temp_high_f: float | None = None
    temp_low_f: float | None = None
    precip_mm: float | None = None
    condition: str | None = None
    raw: Any = None           # provider's per-day blob, stored for re-parsing

    @property
    def horizon_days(self) -> int:
        return (self.target_date - self.fetched_on).days

    @property
    def raw_json(self) -> str | None:
        if self.raw is None:
            return None
        return self.raw if isinstance(self.raw, str) else json.dumps(self.raw)


@dataclass(slots=True)
class ActualDay:
    """Observed weather for one calendar day from one actuals source.

    Multiple sources per date are expected (e.g. ``asos_mci`` and
    ``ecowitt_local``) — the schema keeps them side by side.
    """
    date: date
    source: str               # e.g. 'asos_mci', 'ecowitt_local'
    temp_high_f: float | None = None
    temp_low_f: float | None = None
    precip_mm: float | None = None
    condition: str | None = None
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StationReading:
    """One point-in-time snapshot from the local GW2000X weather station."""
    ts: datetime
    temp_out_f: float | None = None
    humidity_out: int | None = None
    temp_in_f: float | None = None
    humidity_in: int | None = None
    pressure_inhg: float | None = None
    wind_speed_mph: float | None = None
    wind_gust_mph: float | None = None
    wind_dir_deg: int | None = None
    precip_hourly_mm: float | None = None
    precip_daily_mm: float | None = None
    uv_index: float | None = None
    solar_rad_wm2: float | None = None
    raw_json: str | None = None
