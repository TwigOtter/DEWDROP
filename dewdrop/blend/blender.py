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
from statistics import fmean, quantiles

from .. import config

# Numeric metrics we ensemble: forecast column, error column, and whether the
# quantity is physically non-negative (bias correction must not push it < 0).
_METRICS = (
    ("temp_high_f", "temp_high_err", False),
    ("temp_low_f", "temp_low_err", False),
    ("precip_mm", "precip_err", True),
    ("wind_max_mph", "wind_err", True),
)


# Winsorization: clip error samples to the 5th-95th percentile before
# learning bias/variance, so one busted reading (sensor glitch, parser bug)
# can't poison a service's curve for months. Percentiles from fewer than
# _WINSORIZE_MIN_N samples are themselves noise, so small sets pass through.
_WINSORIZE_MIN_N = 10


def _winsorize(vals: list[float]) -> list[float]:
    if len(vals) < _WINSORIZE_MIN_N:
        return vals
    cuts = quantiles(vals, n=20, method="inclusive")
    lo, hi = cuts[0], cuts[-1]   # 5th / 95th percentile
    return [min(max(v, lo), hi) for v in vals]


def _learn(
    conn: sqlite3.Connection, err_col: str, actuals_source: str
) -> dict[tuple[str, int], tuple[float, float, int]]:
    """(service, horizon) -> (bias, variance, n) for one error column."""
    rows = conn.execute(
        f"""
        SELECT service, horizon_days, {err_col} AS err
        FROM forecast_errors
        WHERE actuals_source = ? AND {err_col} IS NOT NULL
          AND horizon_days >= 0
        """,
        (actuals_source,),
    ).fetchall()
    samples: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in rows:
        samples[(r["service"], r["horizon_days"])].append(r["err"])

    stats: dict[tuple[str, int], tuple[float, float, int]] = {}
    for key, vals in samples.items():
        clipped = _winsorize(vals)
        bias = fmean(clipped)
        variance = max(fmean(v * v for v in clipped) - bias * bias, 0.0)
        stats[key] = (bias, variance, len(clipped))
    return stats


def _learn_rain_hits(
    conn: sqlite3.Connection, actuals_source: str
) -> dict[tuple[str, int], tuple[float, int]]:
    """(service, horizon) -> (rain/no-rain hit rate, n)."""
    rows = conn.execute(
        """
        SELECT service, horizon_days,
               AVG(precip_hit)   AS hit_rate,
               COUNT(precip_hit) AS n
        FROM forecast_errors
        WHERE actuals_source = ? AND precip_hit IS NOT NULL
          AND horizon_days >= 0
        GROUP BY service, horizon_days
        """,
        (actuals_source,),
    ).fetchall()
    return {(r["service"], r["horizon_days"]): (r["hit_rate"], r["n"])
            for r in rows}


def _latest_forecasts(conn: sqlite3.Connection, today: date) -> list[sqlite3.Row]:
    """Most recent snapshot per (service, target_date) for today and beyond.

    Excludes 'dewdrop' rows — those are our own ensemble snapshots stored for
    scoring and must not feed back into the ensemble calculation.
    """
    return conn.execute(
        """
        SELECT f.service, f.target_date, f.horizon_days,
               f.temp_high_f, f.temp_low_f, f.precip_mm, f.wind_max_mph,
               f.condition
        FROM forecasts f
        JOIN (
            SELECT service, target_date, MAX(fetched_on) AS latest
            FROM forecasts
            WHERE target_date >= ? AND service != 'dewdrop'
            GROUP BY service, target_date
        ) m
          ON m.service = f.service
         AND m.target_date = f.target_date
         AND m.latest = f.fetched_on
        ORDER BY f.target_date, f.service
        """,
        (today.isoformat(),),
    ).fetchall()


def _weighted(
    values: list[tuple[float, float, float]],
) -> tuple[float, float] | None:
    """Given [(value, weight, residual_var)], return (weighted_mean, combined_sd).

    combined_sd = sqrt(within + between) where:
      within  = variance-weighted average of per-service residual variances
                (conservative — no independence bonus for correlated services)
      between = weighted variance of corrected service values around the mean
    """
    wsum = sum(w for _, w, _ in values)
    if wsum <= 0:
        return None
    mean = sum(v * w for v, w, _ in values) / wsum
    between_var = sum(w * (v - mean) ** 2 for v, w, _ in values) / wsum
    within_var = sum(w * rv for _, w, rv in values) / wsum
    return mean, sqrt(within_var + between_var)


def ensemble_forecast(
    conn: sqlite3.Connection,
    actuals_source: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Bias-corrected ensemble forecast for each upcoming target date."""
    actuals_source = actuals_source or config.ENABLED_ACTUALS[0]
    # "Today" must be the local calendar day (design uses local dates), not UTC,
    # or +0d rolls to tomorrow at 00:00 UTC (7pm CDT). The `now` override (tests)
    # is honoured, treating a naive value as UTC.
    if now is None:
        today = config.local_today()
    else:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        today = now.astimezone(config.tz()).date()
    learned = {col: _learn(conn, col, actuals_source) for _, col, _ in _METRICS}
    rain_hits = _learn_rain_hits(conn, actuals_source)

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

        for fcol, ecol, non_negative in _METRICS:
            stats = learned[ecol]
            corrected: list[tuple[float, float]] = []
            for r in rows:
                raw = r[fcol]
                if raw is None:
                    continue
                bias, variance, n = stats.get((r["service"], r["horizon_days"]),
                                              (0.0, 0.0, 0))
                # A bias estimated from a handful of scored days is mostly
                # noise — don't correct until there's enough history.
                if n < config.MIN_BIAS_SAMPLES:
                    bias = 0.0
                value = raw - bias
                # De-biasing can't make a physical quantity negative
                # (e.g. precip): a correction past zero just means "none".
                if non_negative:
                    value = max(value, 0.0)
                # inverse-variance weight; unknown/zero variance -> weight 1.0
                weight = 1.0 / variance if variance > 0 else 1.0
                corrected.append((value, weight, variance))
            res = _weighted(corrected)
            if res is None:
                day[fcol] = None
                day[fcol + "_sd"] = None
            else:
                mean, sd = res
                day[fcol] = round(mean, 1)
                day[fcol + "_sd"] = round(sd, 1)

        # Chance of rain: each service with a precip number votes rain/no-rain
        # at the threshold, weighted by its historical hit rate at this
        # horizon (unproven services count as a coin flip).
        rain_w = 0.0
        rain_votes = 0.0
        for r in rows:
            if r["precip_mm"] is None:
                continue
            hit_rate, n = rain_hits.get((r["service"], r["horizon_days"]),
                                        (None, 0))
            w = hit_rate if (hit_rate is not None
                             and n >= config.MIN_BIAS_SAMPLES) else 0.5
            rain_w += w
            if r["precip_mm"] >= config.RAIN_THRESHOLD_MM:
                rain_votes += w
        day["rain_chance_pct"] = (
            round(100.0 * rain_votes / rain_w) if rain_w > 0 else None)

        # How much error history backs this day's correction: the weakest
        # contributing service's scored-day count at this horizon.
        ns = [learned["temp_high_err"].get((r["service"], r["horizon_days"]),
                                           (0.0, 0.0, 0))[2]
              for r in rows if r["temp_high_f"] is not None]
        day["history_days"] = min(ns) if ns else 0

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
          AND horizon_days >= 0
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
