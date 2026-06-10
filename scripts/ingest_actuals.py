#!/usr/bin/env python
"""Fetch actuals (ground truth) for a past day (design doc §4, Phase 2 step 1).

Defaults to *yesterday* (local time) — by then the day is complete at all sources.
Pulls from every source in DEWDROP_ENABLED_ACTUALS (ASOS/MCI primary, EcoWitt
secondary) and writes one `actuals` row per source. Idempotent.

Usage: python scripts/ingest_actuals.py [YYYY-MM-DD]
"""
import asyncio
import logging
import sys
from datetime import date, timedelta

import httpx

from dewdrop import config
from dewdrop.actuals import get_enabled
from dewdrop.db import connect, insert_actuals

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dewdrop.actuals")


async def main() -> None:
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        target = config.local_today() - timedelta(days=1)

    fetchers = get_enabled(config.ENABLED_ACTUALS)
    log.info("Fetching actuals for %s from: %s", target, config.ENABLED_ACTUALS)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(fn(client, target) for _, fn in fetchers),
            return_exceptions=True,
        )

    with connect() as conn:
        for (name, _), res in zip(fetchers, results):
            if isinstance(res, Exception):
                log.warning("Actuals source %s failed: %r", name, res)
                continue
            if not res:
                log.info("Actuals source %s: no data for %s (skipped/unconfigured)", name, target)
                continue
            n = insert_actuals(conn, res)
            log.info("Actuals source %s: %d new row(s)", name, n)


if __name__ == "__main__":
    asyncio.run(main())
