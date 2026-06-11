"""Read-only HTTP API + local-network web UI.

Serves JSON for the five design-doc §7 views, station live/history endpoints,
and the single-page Chart.js front end from ``dewdrop/web/static``. The same
JSON endpoints are what Berries can query later over HTTP.

Run:  uvicorn dewdrop.api.main:app --host 0.0.0.0 --port 8004
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..blend import compute_offset, ensemble_forecast, service_bias_curves
from ..db import connect
from ..station.reader import parse as parse_station

app = FastAPI(title="DEWDROP", version="0.3.0")

_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def _local_today() -> str:
    return config.local_today().isoformat()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "location": config.LOCATION_NAME,
            "actuals": config.ENABLED_ACTUALS, "sources": config.ENABLED_SOURCES}


# ── Station: live proxy + history ────────────────────────────────────────────
@app.get("/api/station/live")
def api_station_live() -> dict:
    """Fetch current conditions directly from the GW2000X (real-time proxy)."""
    if not config.GW2000_HOST:
        return {"error": "DEWDROP_GW2000_HOST not configured"}
    try:
        resp = httpx.get(f"http://{config.GW2000_HOST}/get_livedata_info", timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        return {"error": str(exc)}
    r = parse_station(resp.json())
    return {
        "ts": r.ts.isoformat(),
        "temp_out_f": r.temp_out_f,
        "humidity_out": r.humidity_out,
        "temp_in_f": r.temp_in_f,
        "humidity_in": r.humidity_in,
        "pressure_inhg": r.pressure_inhg,
        "wind_speed_mph": r.wind_speed_mph,
        "wind_gust_mph": r.wind_gust_mph,
        "wind_dir_deg": r.wind_dir_deg,
        "precip_hourly_mm": r.precip_hourly_mm,
        "precip_daily_mm": r.precip_daily_mm,
        "uv_index": r.uv_index,
        "solar_rad_wm2": r.solar_rad_wm2,
    }


@app.get("/api/station/today")
def api_station_today() -> dict:
    """All stored readings for today (used for intraday charts)."""
    today = _local_today()
    tz = config.tz()
    local_midnight = datetime.fromisoformat(today).replace(tzinfo=tz)
    utc_lo = local_midnight.astimezone(timezone.utc).isoformat()
    utc_hi = (local_midnight + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    with connect() as conn:
        rows = conn.execute(
            """SELECT ts, temp_out_f, humidity_out, wind_speed_mph, wind_gust_mph,
                      wind_dir_deg, precip_daily_mm, uv_index, solar_rad_wm2
               FROM station_readings
               WHERE ts >= ? AND ts < ?
               ORDER BY ts""",
            (utc_lo, utc_hi),
        ).fetchall()
    return {"date": today, "readings": [dict(r) for r in rows]}


@app.get("/api/station/daily")
def api_station_daily_list(days: int = Query(default=30)) -> dict:
    """Most-recent N days of daily summaries."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM station_daily ORDER BY date DESC LIMIT ?",
            (min(days, 365),),
        ).fetchall()
    return {"days": [dict(r) for r in rows]}


@app.get("/api/station/daily/{target_date}")
def api_station_daily(target_date: str) -> dict:
    """Daily summary for one specific date."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM station_daily WHERE date = ?", (target_date,)
        ).fetchone()
    return dict(row) if row else {}


# ── Dashboard: bias-corrected ensemble for the next N days ───────────────────
@app.get("/api/ensemble")
def api_ensemble(source: str | None = None) -> dict:
    with connect() as conn:
        days = ensemble_forecast(conn, actuals_source=source)
    return {"location": config.LOCATION_NAME,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ground_truth": source or config.ENABLED_ACTUALS[0],
            "days": days}


# Berries-friendly alias for the ensemble.
@app.get("/forecast")
def forecast(source: str | None = None) -> dict:
    return api_ensemble(source)


# ── Microclimate offset: backyard (GW2000) vs regional canonical (MCI) ───────
@app.get("/api/microclimate")
def api_microclimate(days: int = 30) -> dict:
    with connect() as conn:
        return compute_offset(conn, window_days=days)


# ── Service comparison table ──────────────────────────────────────────────────
@app.get("/api/services")
def api_services(
    source: str | None = None,
    horizon_min: int = 0,
    horizon_max: int = Query(default=10),
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    src = source or config.ENABLED_ACTUALS[0]
    clauses = ["actuals_source = ?", "horizon_days BETWEEN ? AND ?"]
    params: list = [src, horizon_min, horizon_max]
    if date_from:
        clauses.append("target_date >= ?"); params.append(date_from)
    if date_to:
        clauses.append("target_date <= ?"); params.append(date_to)
    where = " AND ".join(clauses)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT service,
                   AVG(ABS(temp_high_err)) AS mae_high,
                   AVG(ABS(temp_low_err))  AS mae_low,
                   AVG(ABS(precip_err))    AS mae_precip,
                   AVG(ABS(wind_err))      AS mae_wind,
                   AVG(condition_match) * 100.0 AS condition_pct,
                   COUNT(*) AS n
            FROM forecast_errors
            WHERE {where}
            GROUP BY service
            ORDER BY mae_high
            """,
            params,
        ).fetchall()

    def _r(x, d=2):
        return round(x, d) if x is not None else None

    return {"ground_truth": src, "horizon_min": horizon_min,
            "horizon_max": horizon_max,
            "services": [
                {"service": r["service"], "mae_high": _r(r["mae_high"]),
                 "mae_low": _r(r["mae_low"]), "mae_precip": _r(r["mae_precip"]),
                 "mae_wind": _r(r["mae_wind"]),
                 "condition_pct": _r(r["condition_pct"], 1), "n": r["n"]}
                for r in rows
            ]}


# ── Bias curves (per service, mean signed error by horizon) ──────────────────
@app.get("/api/bias-curves")
def api_bias_curves(metric: str = "temp_high_err", source: str | None = None) -> dict:
    allowed = {"temp_high_err", "temp_low_err", "precip_err", "wind_err"}
    if metric not in allowed:
        metric = "temp_high_err"
    with connect() as conn:
        curves = service_bias_curves(conn, err_col=metric, actuals_source=source)
    return {"metric": metric, "curves": curves}


# ── Daily drill-down: every service at every horizon vs. actual ───────────────
@app.get("/api/daily/{target_date}")
def api_daily(target_date: str) -> dict:
    with connect() as conn:
        forecasts = conn.execute(
            """
            SELECT service, horizon_days, fetched_on,
                   temp_high_f, temp_low_f, precip_mm, wind_max_mph, condition
            FROM forecasts WHERE target_date = ?
            ORDER BY service, horizon_days DESC
            """,
            (target_date,),
        ).fetchall()
        actuals = conn.execute(
            """
            SELECT source, temp_high_f, temp_low_f, precip_mm, wind_max_mph,
                   condition
            FROM actuals WHERE date = ?
            """,
            (target_date,),
        ).fetchall()
    return {"target_date": target_date,
            "forecasts": [dict(r) for r in forecasts],
            "actuals": [dict(r) for r in actuals]}


# ── Raw log (debug view) ──────────────────────────────────────────────────────
@app.get("/api/errors")
def api_errors(limit: int = 200) -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, service, target_date, horizon_days, actuals_source,
                   temp_high_err, temp_low_err, precip_err, wind_err,
                   condition_match
            FROM forecast_errors
            ORDER BY id DESC LIMIT ?
            """,
            (min(limit, 2000),),
        ).fetchall()
    return {"count": len(rows), "errors": [dict(r) for r in rows]}


# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
