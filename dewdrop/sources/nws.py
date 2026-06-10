"""NWS / api.weather.gov — keyless (US only).

Two-step API: GET /points/{lat},{lon} -> the daily forecast URL, then GET that
for 12-hour day/night periods. We fold each day's daytime period into the high
(+ condition) and its nighttime period into the low.

NWS does not expose a forecast precipitation *amount* in this endpoint (only a
probability), so ``precip_mm`` is left null for this source. NWS requires a
descriptive User-Agent.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import httpx

from .. import normalise
from ..models import ForecastDay
from .base import ForecastSource

USER_AGENT = "DEWDROP/0.1 (weather verification; contact twig@twigotter.com)"


class NWSSource(ForecastSource):
    name = "nws"
    requires_key = False
    POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"

    async def fetch(
        self, client: httpx.AsyncClient, lat: float, lon: float, horizon_days: int
    ) -> list[ForecastDay]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
        # NWS truncates coordinates to 4 decimal places and redirects to the
        # canonical URL; httpx doesn't follow redirects by default.
        meta = await client.get(
            self.POINTS_URL.format(lat=lat, lon=lon),
            headers=headers, timeout=30, follow_redirects=True,
        )
        meta.raise_for_status()
        forecast_url = meta.json()["properties"]["forecast"]

        resp = await client.get(
            forecast_url, headers=headers, timeout=30, follow_redirects=True,
        )
        resp.raise_for_status()
        periods = resp.json()["properties"]["periods"]

        fetched_on = self._today_local()
        # date -> partial ForecastDay fields
        days: dict[date, dict] = defaultdict(dict)
        raws: dict[date, list] = defaultdict(list)
        for p in periods:
            d = date.fromisoformat(p["startTime"][:10])
            raws[d].append(p)
            if p.get("isDaytime"):
                days[d]["temp_high_f"] = p.get("temperature")
                days[d]["condition"] = normalise.normalise_text(p.get("shortForecast"))
            else:
                days[d]["temp_low_f"] = p.get("temperature")
                # only fall back to night condition if we have no daytime one
                days[d].setdefault(
                    "condition", normalise.normalise_text(p.get("shortForecast"))
                )

        out: list[ForecastDay] = []
        for d in sorted(days):
            if (d - fetched_on).days > horizon_days:
                continue
            f = days[d]
            out.append(
                ForecastDay(
                    service=self.name,
                    fetched_on=fetched_on,
                    target_date=d,
                    temp_high_f=f.get("temp_high_f"),
                    temp_low_f=f.get("temp_low_f"),
                    precip_mm=None,  # not provided by this endpoint
                    condition=f.get("condition"),
                    raw=raws[d],
                )
            )
        return out
