"""Microclimate offset: GW2000 (backyard) vs ASOS/MCI (regional canonical).

Computed as the mean signed difference ``local − regional`` over the
``window_days`` most recent days where *both* sources have an actuals row.
A negative temp offset means the backyard runs cooler than MCI.

The offsets let the dashboard show "what to expect at home" without
polluting the bias-correction math, which stays anchored on MCI.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from .. import config


def compute_offset(
    conn: sqlite3.Connection,
    window_days: int = 30,
    regional: str = "asos_mci",
    local: str = "gw2000_local",
) -> dict:
    cutoff = (config.local_today() - timedelta(days=window_days)).isoformat()
    row = conn.execute(
        """
        SELECT
            AVG(l.temp_high_f - r.temp_high_f) AS temp_high_offset_f,
            AVG(l.temp_low_f  - r.temp_low_f)  AS temp_low_offset_f,
            AVG(l.precip_mm   - r.precip_mm)   AS precip_offset_mm,
            COUNT(*)                            AS n_days
        FROM actuals r
        JOIN actuals l ON l.date = r.date
        WHERE r.source = ? AND l.source = ? AND r.date >= ?
        """,
        (regional, local, cutoff),
    ).fetchone()

    def _round(v: float | None, ndigits: int) -> float | None:
        return round(v, ndigits) if v is not None else None

    return {
        "regional": regional,
        "local": local,
        "window_days": window_days,
        "n_days": row["n_days"] or 0,
        "temp_high_offset_f": _round(row["temp_high_offset_f"], 1),
        "temp_low_offset_f": _round(row["temp_low_offset_f"], 1),
        "precip_offset_mm": _round(row["precip_offset_mm"], 2),
    }
