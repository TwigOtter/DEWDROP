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

# Sources written into `actuals` by *other* paths (not by ingest_actuals).
# Listed here so ``DEWDROP_ENABLED_ACTUALS`` can include them for the scorer
# and microclimate offset without ingest_actuals trying to fetch them.
LOCAL_SOURCES: frozenset[str] = frozenset({"gw2000_local"})


def get_enabled(names: list[str]) -> list[tuple[str, ActualsFetcher]]:
    """Resolve enabled fetcher sources. ``LOCAL_SOURCES`` are silently
    skipped (they're produced by other scripts); unknown names still raise."""
    out: list[tuple[str, ActualsFetcher]] = []
    for n in names:
        if n in LOCAL_SOURCES:
            continue
        fn = REGISTRY.get(n)
        if fn is None:
            raise KeyError(
                f"Unknown actuals source '{n}'. "
                f"Known fetchers: {sorted(REGISTRY)}; local-only: {sorted(LOCAL_SOURCES)}"
            )
        out.append((n, fn))
    return out
