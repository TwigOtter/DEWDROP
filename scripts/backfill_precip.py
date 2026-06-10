#!/usr/bin/env python3
"""One-off backfill: recompute station_readings.precip_daily_mm from raw_json.

Older readings stored the *weekly* piezoRain bucket (0x11) in precip_daily_mm
because the rain-ID map was shifted one slot; the fix maps 0x10 (the daily
bucket) instead. Every reading kept its full raw_json, so we can recover the
correct daily value by re-parsing each stored payload with the current reader,
then re-aggregate the affected past days so station_daily and the gw2000_local
actuals pick up the corrected totals.

Idempotent: re-running re-derives the same values. Pass --dry-run to preview
without writing.

    python scripts/backfill_precip.py [--dry-run]
"""
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dewdrop import config
from dewdrop.db import connect
from dewdrop.station.reader import parse

# Sibling script (scripts/ is on sys.path when run as `python scripts/...`).
from aggregate_station import aggregate


def main(dry_run: bool = False) -> None:
    tz = ZoneInfo(config.TIMEZONE)
    today_local = datetime.now(tz).date()

    corrected = 0
    affected_past: set = set()

    with connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, raw_json, precip_daily_mm FROM station_readings "
            "WHERE raw_json IS NOT NULL ORDER BY ts"
        ).fetchall()

        for r in rows:
            try:
                payload = json.loads(r["raw_json"])
            except (TypeError, ValueError):
                continue
            reparsed = parse(payload)
            new_daily = reparsed.precip_daily_mm
            if new_daily != r["precip_daily_mm"]:
                corrected += 1
            if not dry_run:
                conn.execute(
                    "UPDATE station_readings "
                    "SET precip_daily_mm = ?, precip_hourly_mm = ? WHERE id = ?",
                    (new_daily, reparsed.precip_hourly_mm, r["id"]),
                )
            local_day = datetime.fromisoformat(r["ts"]).astimezone(tz).date()
            if local_day < today_local:
                affected_past.add(local_day)

        # aggregate() re-inserts gw2000_local with INSERT OR IGNORE, so the
        # stale (overstated) actuals must be removed before re-aggregating.
        # station_daily is INSERT OR REPLACE and self-corrects.
        if not dry_run:
            for d in sorted(affected_past):
                conn.execute(
                    "DELETE FROM actuals WHERE source='gw2000_local' AND date=?",
                    (d.isoformat(),),
                )

    print(f"Re-parsed {len(rows)} readings; "
          f"{corrected} had a corrected daily-precip value.")
    print(f"Past days to re-aggregate: {len(affected_past)} "
          f"(today {today_local} left for the nightly run).")

    if dry_run:
        print("--dry-run: no changes written.")
        return

    for d in sorted(affected_past):
        aggregate(d)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv[1:])
