"""OpenWeatherMap — requires an API key (OPENWEATHERMAP_API_KEY).

STUB: implement against One Call 3.0 ``daily`` and map each day onto
ForecastDay (temp.max/temp.min -> high/low °F, rain -> precip_mm,
weather[0].main -> normalise.normalise_text). Left unimplemented pending a key.
"""
from __future__ import annotations

import httpx

from .. import config
from ..models import ForecastDay
from .base import ForecastSource


class OpenWeatherMapSource(ForecastSource):
    name = "openweathermap"
    requires_key = True
    BASE_URL = "https://api.openweathermap.org/data/3.0/onecall"

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        if not config.OPENWEATHERMAP_API_KEY:
            raise RuntimeError("OPENWEATHERMAP_API_KEY is not set")
        # TODO: GET One Call (units=imperial), parse `daily`, map to ForecastDay.
        raise NotImplementedError("OpenWeatherMap source not yet implemented")
