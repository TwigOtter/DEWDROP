#!/usr/bin/env python3
"""Roll up station_readings into station_daily and write to the actuals table.

Run nightly by dewdrop-aggregate.timer (after midnight local time).
Also accepts an explicit date argument for backfilling: python aggregate_station.py 2025-06-01
"""
import sys
from datetime import date, datetime, timedelta, timezone

from dewdrop import config
from dewdrop.db import connect, insert_actuals
from dewdrop.models import ActualDay


def aggregate(target_date: date) -> None:
    tz = config.tz()
    # Convert local-date boundaries to UTC for the station_readings ts column.
    local_midnight = datetime(target_date.year, target_date.month, target_date.day,
                              tzinfo=tz)
    utc_lo = local_midnight.astimezone(timezone.utc).isoformat()
    utc_hi = (local_midnight + timedelta(days=1)).astimezone(timezone.utc).isoformat()

    with connect() as conn:
        row = conn.execute(
            """SELECT
                   MAX(temp_out_f)    AS temp_high_f,
                   MIN(temp_out_f)    AS temp_low_f,
                   AVG(temp_out_f)    AS temp_avg_f,
                   MAX(humidity_out)  AS humidity_high,
                   MIN(humidity_out)  AS humidity_low,
                   AVG(humidity_out)  AS humidity_avg,
                   MAX(wind_gust_mph) AS wind_max_mph,
                   MAX(wind_speed_mph) AS wind_sustained_max_mph,
                   AVG(wind_speed_mph) AS wind_avg_mph,
                   MAX(precip_daily_mm) AS precip_total_mm,
                   MAX(uv_index)      AS uv_max,
                   MAX(solar_rad_wm2) AS solar_max_wm2,
                   COUNT(*)           AS n_readings
               FROM station_readings
               WHERE ts >= ? AND ts < ?
                 AND temp_out_f IS NOT NULL""",
            (utc_lo, utc_hi),
        ).fetchone()

        if not row or not row["n_readings"]:
            print(f"No readings for {target_date} — nothing to aggregate.", file=sys.stderr)
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO station_daily
               (date, temp_high_f, temp_low_f, temp_avg_f,
                humidity_high, humidity_low, humidity_avg,
                wind_max_mph, wind_avg_mph, precip_total_mm,
                uv_max, solar_max_wm2, n_readings, aggregated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                target_date.isoformat(),
                row["temp_high_f"], row["temp_low_f"], row["temp_avg_f"],
                row["humidity_high"], row["humidity_low"], row["humidity_avg"],
                row["wind_max_mph"], row["wind_avg_mph"], row["precip_total_mm"],
                row["uv_max"], row["solar_max_wm2"],
                row["n_readings"], now_iso,
            ),
        )

        # Feed into the actuals pipeline so forecasts can be scored vs. station data.
        # Enable by adding 'gw2000_local' to DEWDROP_ENABLED_ACTUALS in .env.
        insert_actuals(conn, [
            ActualDay(
                date=target_date,
                source="gw2000_local",
                temp_high_f=row["temp_high_f"],
                temp_low_f=row["temp_low_f"],
                precip_mm=row["precip_total_mm"],
                # Sustained max (not gust), to match the forecast wind metric.
                wind_max_mph=row["wind_sustained_max_mph"],
                condition=None,
                fetched_at=datetime.now(timezone.utc),
            )
        ])

    n = row["n_readings"]
    hi = row["temp_high_f"]
    lo = row["temp_low_f"]
    print(f"Aggregated {n} readings for {target_date}: high={hi:.1f}°F low={lo:.1f}°F")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        target = config.local_today() - timedelta(days=1)
    aggregate(target)
