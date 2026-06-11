"""Weatherbit — /v2.0/forecast/daily (up to 16 days).

With ``units=I`` (imperial) Weatherbit returns temperatures in °F and
precipitation in inches; convert precip back to mm.

Docs: https://www.weatherbit.io/api/weather-forecast-16-day
"""
from __future__ import annotations

from datetime import date

import httpx

from .. import config, normalise
from ..models import ForecastDay
from .base import ForecastSource


class WeatherbitSource(ForecastSource):
    name = "weatherbit"
    requires_key = True
    BASE_URL = "https://api.weatherbit.io/v2.0/forecast/daily"

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        if not config.WEATHERBIT_API_KEY:
            raise RuntimeError("WEATHERBIT_API_KEY is not set")
        params = {
            "lat": lat,
            "lon": lon,
            "key": config.WEATHERBIT_API_KEY,
            "units": "I",
            "days": min(horizon_days + 1, 16),
        }
        resp = await client.get(self.BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        fetched_on = self._today_local()
        out: list[ForecastDay] = []
        for day in data.get("data", []) or []:
            d = date.fromisoformat(day["datetime"])
            if (d - fetched_on).days > horizon_days:
                continue
            weather = day.get("weather") or {}
            cond = normalise.normalise_text(weather.get("description"))
            precip_in = day.get("precip") or 0.0
            out.append(
                ForecastDay(
                    service=self.name,
                    fetched_on=fetched_on,
                    target_date=d,
                    temp_high_f=day.get("max_temp"),
                    temp_low_f=day.get("min_temp"),
                    precip_mm=precip_in * 25.4,
                    # Weatherbit's daily endpoint only exposes the *average*
                    # sustained wind (plus gust), not a daily max — the bias
                    # correction absorbs the systematic low offset.
                    wind_max_mph=day.get("wind_spd"),
                    condition=cond,
                    raw=day,
                )
            )
        return out
