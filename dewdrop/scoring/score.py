"""Nightly scoring (design doc §4, Phase 2).

For every forecast whose ``target_date`` now has an actuals row, compute the
signed error for each metric against that actuals source and write a
``forecast_errors`` row. Errors are **signed** (predicted − actual): positive
means the service ran hot / over-forecast. That sign is what later powers bias
detection rather than mere accuracy.

Idempotent: a (forecast_id, actuals_source) pair is scored at most once.
"""
from __future__ import annotations

import sqlite3


def _err(pred: float | None, actual: float | None) -> float | None:
    if pred is None or actual is None:
        return None
    return pred - actual


def score_pending(conn: sqlite3.Connection) -> int:
    """Score every forecast that has matching actuals but no error row yet.

    Returns the number of new ``forecast_errors`` rows written.
    """
    rows = conn.execute(
        """
        SELECT
            f.id            AS forecast_id,
            f.service       AS service,
            f.target_date   AS target_date,
            f.horizon_days  AS horizon_days,
            f.temp_high_f   AS f_high,
            f.temp_low_f    AS f_low,
            f.precip_mm     AS f_precip,
            f.condition     AS f_cond,
            a.source        AS actuals_source,
            a.temp_high_f   AS a_high,
            a.temp_low_f    AS a_low,
            a.precip_mm     AS a_precip,
            a.condition     AS a_cond
        FROM forecasts f
        JOIN actuals a ON a.date = f.target_date
        LEFT JOIN forecast_errors e
               ON e.forecast_id = f.id AND e.actuals_source = a.source
        WHERE e.id IS NULL
        """
    ).fetchall()

    written = 0
    for r in rows:
        high_err = _err(r["f_high"], r["a_high"])
        low_err = _err(r["f_low"], r["a_low"])
        precip_err = _err(r["f_precip"], r["a_precip"])
        if r["f_cond"] is not None and r["a_cond"] is not None:
            cond_match = 1 if r["f_cond"] == r["a_cond"] else 0
        else:
            cond_match = None

        # Nothing comparable for this pair — don't write an empty row.
        if high_err is None and low_err is None and precip_err is None and cond_match is None:
            continue

        conn.execute(
            """
            INSERT OR IGNORE INTO forecast_errors
              (forecast_id, service, target_date, horizon_days, actuals_source,
               temp_high_err, temp_low_err, precip_err, condition_match)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (r["forecast_id"], r["service"], r["target_date"], r["horizon_days"],
             r["actuals_source"], high_err, low_err, precip_err, cond_match),
        )
        written += 1
    return written
