"""SQLite layer: schema + connection + insert/query helpers.

The schema follows the design doc §3 — three wide tables in a daily model:

  1. forecasts        — one row per (service, fetched_on, target_date)
  2. actuals          — observed weather, one row per (date, source)
  3. forecast_errors  — signed per-metric error, one row per
                        (forecast, actuals_source), written nightly

Dates are stored as ISO ``YYYY-MM-DD`` strings; timestamps as ISO-8601 UTC.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator

from . import config
from .models import ActualDay, ForecastDay

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT    NOT NULL,        -- 'nws', 'open_meteo', 'owm', ...
    fetched_on    DATE    NOT NULL,        -- snapshot date (UTC)
    target_date   DATE    NOT NULL,        -- day being predicted
    horizon_days  INTEGER NOT NULL,        -- target_date - fetched_on
    temp_high_f   REAL,
    temp_low_f    REAL,
    precip_mm     REAL,
    condition     TEXT,                    -- normalised label (see normalise.py)
    raw_json      TEXT,                    -- provider blob, for re-processing
    UNIQUE (service, fetched_on, target_date)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_target
    ON forecasts(target_date);
CREATE INDEX IF NOT EXISTS idx_forecasts_service_horizon
    ON forecasts(service, horizon_days);

CREATE TABLE IF NOT EXISTS actuals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         DATE     NOT NULL,
    source       TEXT     NOT NULL,        -- 'asos_mci', 'ecowitt_local', ...
    temp_high_f  REAL,
    temp_low_f   REAL,
    precip_mm    REAL,
    condition    TEXT,
    fetched_at   DATETIME NOT NULL,        -- ISO-8601 UTC
    UNIQUE (date, source)
);
CREATE INDEX IF NOT EXISTS idx_actuals_date ON actuals(date);

CREATE TABLE IF NOT EXISTS forecast_errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id     INTEGER NOT NULL REFERENCES forecasts(id),
    service         TEXT    NOT NULL,      -- denormalised for simpler queries
    target_date     DATE    NOT NULL,      -- denormalised
    horizon_days    INTEGER NOT NULL,      -- denormalised
    actuals_source  TEXT    NOT NULL,      -- which actuals row was used
    temp_high_err   REAL,                  -- predicted - actual (+ = ran hot)
    temp_low_err    REAL,                  -- predicted - actual (+ = ran hot)
    precip_err      REAL,                  -- predicted - actual (+ = over)
    condition_match INTEGER,               -- 1 match, 0 miss, NULL if unknown
    UNIQUE (forecast_id, actuals_source)
);
CREATE INDEX IF NOT EXISTS idx_errors_service_horizon
    ON forecast_errors(service, horizon_days);
"""


def _d(d: date) -> str:
    return d.isoformat()


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")     # concurrent pollers + reader
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def insert_forecasts(conn: sqlite3.Connection, records: Iterable[ForecastDay]) -> int:
    """INSERT OR IGNORE forecast-day rows. Returns the number that were new.

    The unique constraint on (service, fetched_on, target_date) makes the
    nightly snapshot idempotent.
    """
    rows = [
        (r.service, _d(r.fetched_on), _d(r.target_date), r.horizon_days,
         r.temp_high_f, r.temp_low_f, r.precip_mm, r.condition, r.raw_json)
        for r in records
    ]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO forecasts
           (service, fetched_on, target_date, horizon_days,
            temp_high_f, temp_low_f, precip_mm, condition, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return cur.rowcount


def insert_actuals(conn: sqlite3.Connection, actuals: Iterable[ActualDay]) -> int:
    """INSERT OR IGNORE actuals rows (one per date+source). Returns new count."""
    rows = [
        (_d(a.date), a.source, a.temp_high_f, a.temp_low_f, a.precip_mm,
         a.condition, a.fetched_at.isoformat())
        for a in actuals
    ]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO actuals
           (date, source, temp_high_f, temp_low_f, precip_mm, condition, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return cur.rowcount
