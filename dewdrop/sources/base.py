"""Common interface every forecast source implements."""
from __future__ import annotations

import abc
from datetime import date

import httpx

from .. import config
from ..models import ForecastDay


class ForecastSource(abc.ABC):
    """Fetch a daily forecast for one location.

    Subclasses set ``name`` and implement :meth:`fetch`, returning one
    :class:`ForecastDay` per target day from today (horizon 0) through
    ``today + horizon_days``. They normalise each provider's condition
    vocabulary via :mod:`dewdrop.normalise`.
    """

    #: short, stable key used in config + the `service` column
    name: str = "base"

    #: does this source need an API key to function?
    requires_key: bool = False

    @abc.abstractmethod
    async def fetch(
        self,
        client: httpx.AsyncClient,
        lat: float,
        lon: float,
        horizon_days: int,
    ) -> list[ForecastDay]:
        ...

    @staticmethod
    def _today_local() -> date:
        """Snapshot date: the local calendar day. Sources fetch local-day
        forecasts (e.g. open_meteo with ``timezone=TIMEZONE``), so fetched_on —
        and thus horizon_days = target_date - fetched_on — must be local too,
        or horizons go off by one after 00:00 UTC."""
        return config.local_today()
