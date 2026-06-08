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
        "sdate": target_date.isoformat(),
        "edate": target_date.isoformat(),
    }
    resp = await client.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not rows:
        return []

    rec = rows[0]
    high = _first(rec, "max_tmpf", "high", "max_temp_f")
    low = _first(rec, "min_tmpf", "low", "min_temp_f")
    precip_in = _first(rec, "precip", "pday", "precip_in")
    precip_mm = precip_in * _IN_TO_MM if precip_in is not None else None

    return [
        ActualDay(
            date=target_date,
            source=SOURCE,
            temp_high_f=high,
            temp_low_f=low,
            precip_mm=precip_mm,
            condition=None,  # daily summary carries no single condition label
            fetched_at=datetime.now(timezone.utc),
        )
    ]
