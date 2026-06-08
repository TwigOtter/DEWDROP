"""Tomorrow.io — requires an API key (TOMORROW_IO_API_KEY).

STUB: implement against /v4/weather/forecast (timesteps=1d) and map each day's
``values`` onto ForecastDay (temperatureMax/Min, rainAccumulation -> precip_mm,
weatherCodeMax -> a normalised condition). Left unimplemented pending a key.
"""
from __future__ import annotations

import httpx

from .. import config
from ..models import ForecastDay
from .base import ForecastSource


class TomorrowIoSource(ForecastSource):
    name = "tomorrow_io"
    requires_key = True
    BASE_URL = "https://api.tomorrow.io/v4/weather/forecast"

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        if not config.TOMORROW_IO_API_KEY:
            raise RuntimeError("TOMORROW_IO_API_KEY is not set")
        # TODO: GET forecast (timesteps=1d), parse timelines.daily, map to ForecastDay.
        raise NotImplementedError("Tomorrow.io source not yet implemented")
