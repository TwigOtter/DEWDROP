#!/usr/bin/env python
"""Snapshot today's DEWDROP ensemble forecast as a scoreable service row.

Run nightly via the `dewdrop-score` timer (or a dedicated timer) AFTER
poll_forecasts.py so it captures the most current ensemble. Stores one
ForecastDay per target date under service='dewdrop'. INSERT OR IGNORE makes
re-running the same night a no-op.

The blender explicitly excludes 'dewdrop' rows when computing the ensemble,
so there is no feedback loop.
"""
import logging
from datetime import date

from dewdrop import config
from dewdrop.blend import ensemble_forecast
from dewdrop.db import connect, insert_forecasts
from dewdrop.models import ForecastDay

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dewdrop.snapshot_ensemble")


def main() -> None:
    today = config.local_today()
    with connect() as conn:
        days = ensemble_forecast(conn)
        records: list[ForecastDay] = []
        for d in days:
            target = date.fromisoformat(d["target_date"])
            records.append(ForecastDay(
                service="dewdrop",
                fetched_on=today,
                target_date=target,
                temp_high_f=d.get("temp_high_f"),
                temp_low_f=d.get("temp_low_f"),
                precip_mm=d.get("precip_mm"),
                wind_max_mph=d.get("wind_max_mph"),
                condition=d.get("condition"),
                raw=d,
            ))
        n = insert_forecasts(conn, records)
    log.info("Snapshotted %d new DEWDROP ensemble row(s) (of %d days)", n, len(records))


if __name__ == "__main__":
    main()
