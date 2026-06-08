#!/usr/bin/env python
"""Snapshot every enabled forecast source (design doc §4, Phase 1).

Run nightly via the `dewdrop-poll` timer. Each source queries today through
today+HORIZON_DAYS; rows are written with INSERT OR IGNORE so re-running the
same night is a no-op. One flaky provider doesn't sink the whole run.
"""
import asyncio
import logging

import httpx

from dewdrop import config
from dewdrop.db import connect, insert_forecasts
from dewdrop.sources import get_enabled

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dewdrop.poll")


async def main() -> None:
    sources = get_enabled(config.ENABLED_SOURCES)
    log.info("Polling %d source(s): %s", len(sources), config.ENABLED_SOURCES)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(s.fetch(client, config.LATITUDE, config.LONGITUDE, config.HORIZON_DAYS)
              for s in sources),
            return_exceptions=True,
        )

    with connect() as conn:
        for src, res in zip(sources, results):
            if isinstance(res, Exception):
                log.warning("Source %s failed: %r", src.name, res)
                continue
            n = insert_forecasts(conn, res)
            log.info("Source %s: %d new forecast-day rows (of %d)", src.name, n, len(res))


if __name__ == "__main__":
    asyncio.run(main())
