"""Common interface every forecast source implements."""
from __future__ import annotations

import abc
from datetime import datetime, timezone

import httpx

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
    def _today_utc() -> "datetime.date":
        return datetime.now(timezone.utc).date()
