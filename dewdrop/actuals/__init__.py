"""Actuals (ground-truth) sources. Each exposes ``fetch(client, target_date)``
returning a list of :class:`~dewdrop.models.ActualDay`.

Multiple sources run in parallel per the design doc — ASOS/MCI is the primary
ground truth, the EcoWitt GW2000 a secondary microclimate reading.
"""
from __future__ import annotations

from datetime import date
from typing import Awaitable, Callable

import httpx

from ..models import ActualDay
from . import asos, ecowitt

ActualsFetcher = Callable[[httpx.AsyncClient, date], Awaitable[list[ActualDay]]]

# Registry keyed by the `source` string written into the `actuals` table.
REGISTRY: dict[str, ActualsFetcher] = {
    asos.SOURCE: asos.fetch,
    ecowitt.SOURCE: ecowitt.fetch,
}


def get_enabled(names: list[str]) -> list[tuple[str, ActualsFetcher]]:
    out: list[tuple[str, ActualsFetcher]] = []
    for n in names:
        fn = REGISTRY.get(n)
        if fn is None:
            raise KeyError(f"Unknown actuals source '{n}'. Known: {sorted(REGISTRY)}")
        out.append((n, fn))
    return out
