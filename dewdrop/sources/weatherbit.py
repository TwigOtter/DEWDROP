"""Weatherbit — requires an API key (WEATHERBIT_API_KEY).

STUB: implement against /v2.0/forecast/daily (days=11) and map each day onto
ForecastDay (max_temp/min_temp -> high/low °F, precip mm direct,
weather.description -> normalise.normalise_text). Left unimplemented pending a key.
"""
from __future__ import annotations

import httpx

from .. import config
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
        # TODO: GET daily (units=I but precip is mm), parse `data`, map to ForecastDay.
        raise NotImplementedError("Weatherbit source not yet implemented")
