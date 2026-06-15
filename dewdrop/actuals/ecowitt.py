"""EcoWitt GW2000 actuals — apartment-microclimate ground truth (secondary).

The GW2000's *local* endpoint only serves instantaneous live data, which can't
give a day's high/low after the fact. So daily actuals come from the EcoWitt
**cloud history API**, which stores the station's time series and lets us
aggregate a calendar day into high/low/precip.

Requires EcoWitt cloud credentials (application + API key + device MAC). If any
are unset this source is skipped (returns []), so the pipeline still runs on
ASOS alone. Field paths depend on your sensor layout — verify against your
device's history response.

Docs: https://doc.ecowitt.net/web/#/apiv3en?page_id=17
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

import httpx

from .. import config
from ..models import ActualDay

SOURCE = "ecowitt_local"
BASE_URL = "https://api.ecowitt.net/api/v3/device/history"

# Ecowitt unit ids: temperature 2 = °F; rainfall 13 = mm; wind 9 = mph.
_TEMP_UNIT_F = 2
_RAIN_UNIT_MM = 13
_WIND_UNIT_MPH = 9


def _series_values(group: dict, *path: str) -> list[float]:
    """Walk ``group[path...]['list']`` (a {timestamp: value} map) -> [floats]."""
    node = group
    for key in path:
        if not isinstance(node, dict):
            return []
        node = node.get(key, {})
    listing = node.get("list", {}) if isinstance(node, dict) else {}
    out: list[float] = []
    for v in listing.values():
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


async def fetch(client: httpx.AsyncClient, target_date: date) -> list[ActualDay]:
    if not (config.ECOWITT_APP_KEY and config.ECOWITT_API_KEY and config.ECOWITT_MAC):
        return []  # not configured — skip silently

    start = datetime.combine(target_date, time.min)
    end = datetime.combine(target_date, time.max)
    params = {
        "application_key": config.ECOWITT_APP_KEY,
        "api_key": config.ECOWITT_API_KEY,
        "mac": config.ECOWITT_MAC,
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "call_back": "outdoor,rainfall,wind",
        "cycle_type": "auto",
        "temp_unitid": _TEMP_UNIT_F,
        "rainfall_unitid": _RAIN_UNIT_MM,
        "wind_speed_unitid": _WIND_UNIT_MPH,
    }
    resp = await client.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data") or {}

    temps = _series_values(data, "outdoor", "temperature")
    # Daily rainfall is cumulative through the day; its max is the day's total.
    rain = _series_values(data, "rainfall", "daily")
    winds = _series_values(data, "wind", "wind_speed")

    if not temps and not rain:
        return []

    return [
        ActualDay(
            date=target_date,
            source=SOURCE,
            temp_high_f=max(temps) if temps else None,
            temp_low_f=min(temps) if temps else None,
            precip_mm=max(rain) if rain else None,
            wind_max_mph=max(winds) if winds else None,
            condition=None,
            fetched_at=datetime.now(timezone.utc),
        )
    ]
