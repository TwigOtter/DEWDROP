"""Tomorrow.io — /v4/weather/forecast daily timeseries.

With ``units=imperial`` temperatures come back in °F and accumulations in
*inches*, so we convert precip back to mm. Conditions use Tomorrow.io's
proprietary weather codes mapped via ``_CODE_MAP``.

Docs: https://docs.tomorrow.io/reference/weather-forecast
Codes: https://docs.tomorrow.io/reference/data-layers-weather-codes
"""
from __future__ import annotations

from datetime import date

import httpx

from .. import config, models
from ..models import ForecastDay
from .base import ForecastSource


_CODE_MAP: dict[int, str] = {
    1000: models.CLEAR,        1100: models.CLEAR,
    1101: models.PARTLY_CLOUDY,
    1001: models.CLOUDY,       1102: models.CLOUDY,
    2000: models.FOG,          2100: models.FOG,
    4000: models.RAIN,         4001: models.RAIN,  4200: models.RAIN,
    4201: models.HEAVY_RAIN,   8000: models.HEAVY_RAIN,
    5000: models.SNOW,         5001: models.SNOW,  5100: models.SNOW, 5101: models.SNOW,
    6000: models.SNOW,         6001: models.SNOW,  6200: models.SNOW, 6201: models.SNOW,
    7000: models.SNOW,         7101: models.SNOW,  7102: models.SNOW,
}


class TomorrowIoSource(ForecastSource):
    name = "tomorrow_io"
    requires_key = True
    BASE_URL = "https://api.tomorrow.io/v4/weather/forecast"

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        if not config.TOMORROW_IO_API_KEY:
            raise RuntimeError("TOMORROW_IO_API_KEY is not set")
        params = {
            "location": f"{lat},{lon}",
            "timesteps": "1d",
            "units": "imperial",
            "apikey": config.TOMORROW_IO_API_KEY,
        }
        resp = await client.get(self.BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        fetched_on = self._today_local()
        out: list[ForecastDay] = []
        for day in data.get("timelines", {}).get("daily", []) or []:
            d = date.fromisoformat(day["time"][:10])
            if (d - fetched_on).days > horizon_days:
                continue
            v = day.get("values") or {}
            code = v.get("weatherCodeMax") or v.get("weatherCodeMin")
            cond = _CODE_MAP.get(int(code)) if code is not None else None
            rain_in = v.get("rainAccumulationSum") or 0.0
            snow_in = v.get("snowAccumulationSum") or 0.0
            out.append(
                ForecastDay(
                    service=self.name,
                    fetched_on=fetched_on,
                    target_date=d,
                    temp_high_f=v.get("temperatureMax"),
                    temp_low_f=v.get("temperatureMin"),
                    precip_mm=(rain_in + snow_in) * 25.4,
                    wind_max_mph=v.get("windSpeedMax", v.get("windSpeedAvg")),
                    condition=cond,
                    raw=day,
                )
            )
        return out
