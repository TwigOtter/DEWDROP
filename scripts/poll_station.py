#!/usr/bin/env python3
"""Snapshot GW2000X live data into station_readings.

Designed to exit immediately — run every minute via dewdrop-station.timer.
"""
import sys

import httpx

from dewdrop import config
from dewdrop.db import connect, insert_station_reading
from dewdrop.station.reader import parse


def main() -> None:
    if not config.GW2000_HOST:
        print("DEWDROP_GW2000_HOST not set — skipping.", file=sys.stderr)
        return

    url = f"http://{config.GW2000_HOST}/get_livedata_info"
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        print(f"Station fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    reading = parse(resp.json())

    with connect() as conn:
        new = insert_station_reading(conn, reading)

    if new:
        print(f"Stored reading at {reading.ts.isoformat()} "
              f"(out={reading.temp_out_f}°F, wind={reading.wind_speed_mph}mph)")
    else:
        print(f"Duplicate reading at {reading.ts.isoformat()} — skipped.")


if __name__ == "__main__":
    main()
