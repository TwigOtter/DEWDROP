"""Open-Meteo — keyless, multi-model. The reference implementation other
sources are modelled on.

Uses the *daily* endpoint: one record per calendar day with the day's high/low,
total precipitation (mm) and a WMO weather code we normalise to our condition
set.

Docs: https://open-meteo.com/en/docs
"""
from __future__ import annotations

from datetime import date

import httpx

from .. import config, normalise
from ..models import ForecastDay
from .base import ForecastSource

_DAILY_VARS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "weathercode",
)


class OpenMeteoSource(ForecastSource):
    name = "open_meteo"
    requires_key = False
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(_DAILY_VARS),
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "mm",
            "timezone": config.TIMEZONE,
            "forecast_days": horizon_days + 1,   # today (h0) .. today+horizon
        }
        resp = await client.get(self.BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})

        dates = daily.get("time", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        codes = daily.get("weathercode", [])
        fetched_on = self._today_utc()

        out: list[ForecastDay] = []
        for i, d in enumerate(dates):
            code = codes[i] if i < len(codes) else None
            out.append(
                ForecastDay(
                    service=self.name,
                    fetched_on=fetched_on,
                    target_date=date.fromisoformat(d),
                    temp_high_f=highs[i] if i < len(highs) else None,
                    temp_low_f=lows[i] if i < len(lows) else None,
                    precip_mm=precip[i] if i < len(precip) else None,
                    condition=normalise.from_wmo_code(code),
                    raw={var: daily.get(var, [None] * len(dates))[i] for var in _DAILY_VARS},
                )
            )
        return out
