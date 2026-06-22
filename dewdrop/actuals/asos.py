"""NOAA ASOS actuals via the Iowa Environmental Mesonet (IEM) daily API.

This is the project's **primary ground truth**: the official airport
observations for the MCI station, computed by IEM into a daily summary
(high/low °F, precipitation). Keyless.

The IEM daily JSON service returns one record per day for a station; field
names have varied over time, so we parse defensively across the common keys.

Docs: https://mesonet.agron.iastate.edu/api/1/docs
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from .. import config
from ..models import ActualDay

SOURCE = "asos_mci"
BASE_URL = "https://mesonet.agron.iastate.edu/api/1/daily.json"

# ASOS precip is reported in inches; we store mm.
_IN_TO_MM = 25.4
# IEM wind speeds are in knots; we store mph.
_KT_TO_MPH = 1.15078


def _first(d: dict, *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


async def fetch(client: httpx.AsyncClient, target_date: date) -> list[ActualDay]:
    """Fetch the daily summary for ``target_date`` from IEM. May return []."""
    params = {
        "network": config.ASOS_NETWORK,
        "station": config.ASOS_STATION,
        "date": target_date.isoformat(),
    }
    resp = await client.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not rows:
        return []

    # IEM silently ignores unknown date params and dumps the station's full
    # history (oldest first), so never trust rows[0] blindly — match the date.
    iso = target_date.isoformat()
    rec = next((r for r in rows if r.get("date") == iso), None)
    if rec is None:
        return []
    high = _first(rec, "max_tmpf", "high", "max_temp_f")
    low = _first(rec, "min_tmpf", "low", "min_temp_f")
    precip_in = _first(rec, "precip", "pday", "precip_in")
    precip_mm = precip_in * _IN_TO_MM if precip_in is not None else None
    # IEM daily summary exposes max gust (not max sustained wind), in knots.
    # "max_gust" is the only daily-max wind field available; forecast sources
    # (open_meteo) provide max sustained wind, so a small systematic bias is
    # expected — the bias-correction layer will learn and remove it.
    wind_kt = _first(rec, "max_gust", "avg_sknt")
    wind_mph = wind_kt * _KT_TO_MPH if wind_kt is not None else None

    return [
        ActualDay(
            date=target_date,
            source=SOURCE,
            temp_high_f=high,
            temp_low_f=low,
            precip_mm=precip_mm,
            wind_max_mph=wind_mph,
            condition=None,  # daily summary carries no single condition label
            fetched_at=datetime.now(timezone.utc),
        )
    ]
