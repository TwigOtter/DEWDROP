"""Bias-corrected, inverse-variance-weighted ensemble forecast (design doc §5).

Once enough error history has accumulated, each service's systematic bias at a
given horizon is removed, and the de-biased forecasts are combined with weights
inversely proportional to each service's historical *variance* at that horizon
— consistent services count more, noisy ones less. The spread of the combined
forecasts becomes the uncertainty band.

Bias/variance are learned from ``forecast_errors`` against a chosen ground-truth
source (ASOS/MCI by default).
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from math import sqrt
from zoneinfo import ZoneInfo

from .. import config

# Numeric metrics we ensemble: forecast column, error column.
_METRICS = (
    ("temp_high_f", "temp_high_err"),
    ("temp_low_f", "temp_low_err"),
    ("precip_mm", "precip_err"),
)


def _learn(
    conn: sqlite3.Connection, err_col: str, actuals_source: str
) -> dict[tuple[str, int], tuple[float, float, int]]:
    """(service, horizon) -> (bias, variance, n) for one error column."""
    rows = conn.execute(
        f"""
        SELECT service, horizon_days,
               AVG({err_col})            AS bias,
               AVG({err_col} * {err_col}) AS mean_sq,
               COUNT({err_col})          AS n
        FROM forecast_errors
        WHERE actuals_source = ? AND {err_col} IS NOT NULL
        GROUP BY service, horizon_days
        """,
        (actuals_source,),
    ).fetchall()
    stats: dict[tuple[str, int], tuple[float, float, int]] = {}
    for r in rows:
        bias = r["bias"] or 0.0
        variance = max((r["mean_sq"] or 0.0) - bias * bias, 0.0)
        stats[(r["service"], r["horizon_days"])] = (bias, variance, r["n"])
    return stats


def _latest_forecasts(conn: sqlite3.Connection, today: date) -> list[sqlite3.Row]:
    """Most recent snapshot per (service, target_date) for today and beyond."""
    return conn.execute(
        """
        SELECT f.service, f.target_date, f.horizon_days,
               f.temp_high_f, f.temp_low_f, f.precip_mm, f.condition
        FROM forecasts f
        JOIN (
            SELECT service, target_date, MAX(fetched_on) AS latest
            FROM forecasts
            WHERE target_date >= ?
            GROUP BY service, target_date
        ) m
          ON m.service = f.service
         AND m.target_date = f.target_date
         AND m.latest = f.fetched_on
        ORDER BY f.target_date, f.service
        """,
        (today.isoformat(),),
    ).fetchall()


def _weighted(values: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Given [(value, weight)], return (weighted_mean, weighted_std)."""
    wsum = sum(w for _, w in values)
    if wsum <= 0:
        return None
    mean = sum(v * w for v, w in values) / wsum
    var = sum(w * (v - mean) ** 2 for v, w in values) / wsum
    return mean, sqrt(var)


def ensemble_forecast(
    conn: sqlite3.Connection,
    actuals_source: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Bias-corrected ensemble forecast for each upcoming target date."""
    actuals_source = actuals_source or config.ENABLED_ACTUALS[0]
    # "Today" must be the local calendar day (design uses local dates), not UTC,
    # or +0d rolls to tomorrow at 00:00 UTC (7pm CDT). Treat a naive `now` as UTC.
    tz = ZoneInfo(config.TIMEZONE)
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(tz).date()
    learned = {col: _learn(conn, col, actuals_source) for _, col in _METRICS}

    # Group latest forecasts by target_date.
    by_date: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in _latest_forecasts(conn, today):
        by_date[row["target_date"]].append(row)

    out: list[dict] = []
    for target_date in sorted(by_date):
        rows = by_date[target_date]
        horizon = rows[0]["horizon_days"]
        day: dict = {"target_date": target_date, "horizon_days": horizon,
                     "n_services": len(rows)}

        for fcol, ecol in _METRICS:
            stats = learned[ecol]
            corrected: list[tuple[float, float]] = []
            for r in rows:
                raw = r[fcol]
                if raw is None:
                    continue
                bias, variance, n = stats.get((r["service"], r["horizon_days"]),
                                              (0.0, 0.0, 0))
                # inverse-variance weight; unknown/zero variance -> weight 1.0
                weight = 1.0 / variance if variance > 0 else 1.0
                corrected.append((raw - bias, weight))
            res = _weighted(corrected)
            if res is None:
                day[fcol] = None
                day[fcol + "_sd"] = None
            else:
                mean, sd = res
                day[fcol] = round(mean, 1)
                day[fcol + "_sd"] = round(sd, 1)

        # Condition: inverse-variance-weighted vote (using temp_high weights).
        votes: Counter = Counter()
        for r in rows:
            if not r["condition"]:
                continue
            _, variance, _ = learned["temp_high_err"].get(
                (r["service"], r["horizon_days"]), (0.0, 0.0, 0))
            votes[r["condition"]] += 1.0 / variance if variance > 0 else 1.0
        day["condition"] = votes.most_common(1)[0][0] if votes else None

        out.append(day)
    return out


def service_bias_curves(
    conn: sqlite3.Connection,
    err_col: str = "temp_high_err",
    actuals_source: str | None = None,
) -> dict[str, list[dict]]:
    """Per-service mean signed error by horizon — feeds the bias-curve chart."""
    actuals_source = actuals_source or config.ENABLED_ACTUALS[0]
    rows = conn.execute(
        f"""
        SELECT service, horizon_days,
               AVG({err_col}) AS mean_err,
               COUNT({err_col}) AS n
        FROM forecast_errors
        WHERE actuals_source = ? AND {err_col} IS NOT NULL
        GROUP BY service, horizon_days
        ORDER BY service, horizon_days
        """,
        (actuals_source,),
    ).fetchall()
    curves: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        curves[r["service"]].append(
            {"horizon_days": r["horizon_days"],
             "mean_err": round(r["mean_err"], 2), "n": r["n"]}
        )
    return dict(curves)
