"""Wunderground — CAVEAT: the free Weather Underground *forecast* API was
discontinued (~2018). Forecast retrieval now generally requires The Weather
Company / paid access. Your GW2000 can *upload* PWS data to WU, but that is a
different capability from grading WU's forecasts.

STUB: kept in the registry so the project's source list is complete, but it
will refuse to run until we settle on a real, accessible endpoint. Confirm the
intended WU access path against the setup docx.
"""
from __future__ import annotations

import httpx

from .. import config
from ..models import ForecastDay
from .base import ForecastSource


class WundergroundSource(ForecastSource):
    name = "wunderground"
    requires_key = True

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        if not config.WUNDERGROUND_API_KEY:
            raise RuntimeError(
                "WUNDERGROUND_API_KEY is not set — and note the free WU forecast "
                "API is discontinued; see this module's docstring."
            )
        # TODO: confirm an accessible forecast endpoint before implementing.
        raise NotImplementedError("Wunderground forecast source not yet implemented")
