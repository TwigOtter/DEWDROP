"""OpenWeatherMap — /data/2.5/forecast, the free 5-day / 3-hour endpoint.

OWM's daily One Call 3.0 endpoint requires a paid subscription. The 2.5
forecast endpoint stays on the free tier (1k calls/day, 60/min) and returns
40 × 3-hour slices that we aggregate into 5 daily ForecastDay rows.

Aggregation:
- ``temp_high_f``  = max of ``main.temp_max`` across the day's slices
- ``temp_low_f``   = min of ``main.temp_min``
- ``precip_mm``    = sum of ``rain.3h + snow.3h`` (both already in mm)
- ``condition``    = most-severe slice condition for the day

Slices are bucketed by *local* date so day boundaries match the user's clock.

Docs: https://openweathermap.org/forecast5
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

import httpx

from .. import config, models, normalise
from ..models import ForecastDay
from .base import ForecastSource


_SEVERITY = {
    models.HEAVY_RAIN: 6,
    models.SNOW: 5,
    models.RAIN: 4,
    models.FOG: 3,
    models.CLOUDY: 2,
    models.PARTLY_CLOUDY: 1,
    models.CLEAR: 0,
}


def _worst(conditions: list[str | None]) -> str | None:
    valid = [c for c in conditions if c is not None]
    if not valid:
        return None
    return max(valid, key=lambda c: _SEVERITY.get(c, -1))


class OpenWeatherMapSource(ForecastSource):
    name = "openweathermap"
    requires_key = True
    BASE_URL = "https://api.openweathermap.org/data/2.5/forecast"

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        if not config.OPENWEATHERMAP_API_KEY:
            raise RuntimeError("OPENWEATHERMAP_API_KEY is not set")
        params = {
            "lat": lat,
            "lon": lon,
            "appid": config.OPENWEATHERMAP_API_KEY,
            "units": "imperial",
        }
        resp = await client.get(self.BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        tz = config.tz()
        fetched_on = self._today_local()

        by_day: dict[date, list[dict]] = defaultdict(list)
        for slice_ in data.get("list", []) or []:
            d = datetime.fromtimestamp(slice_["dt"], tz=tz).date()
            by_day[d].append(slice_)

        out: list[ForecastDay] = []
        for d in sorted(by_day):
            if (d - fetched_on).days > horizon_days:
                continue
            slices = by_day[d]
            highs = [s["main"]["temp_max"] for s in slices if "main" in s]
            lows = [s["main"]["temp_min"] for s in slices if "main" in s]
            precip = sum(
                (s.get("rain", {}).get("3h") or 0.0)
                + (s.get("snow", {}).get("3h") or 0.0)
                for s in slices
            )
            # units=imperial -> wind.speed is already mph
            winds = [s["wind"]["speed"] for s in slices
                     if s.get("wind", {}).get("speed") is not None]
            condition = _worst([
                normalise.normalise_text(
                    (s.get("weather") or [{}])[0].get("description")
                    or (s.get("weather") or [{}])[0].get("main")
                )
                for s in slices
            ])
            out.append(
                ForecastDay(
                    service=self.name,
                    fetched_on=fetched_on,
                    target_date=d,
                    temp_high_f=max(highs) if highs else None,
                    temp_low_f=min(lows) if lows else None,
                    precip_mm=precip,
                    wind_max_mph=max(winds) if winds else None,
                    condition=condition,
                    raw=slices,
                )
            )
        return out
