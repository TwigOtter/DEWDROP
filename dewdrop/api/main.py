"""Read-only HTTP API + local-network web UI.

Serves JSON for the five design-doc §7 views and the single-page Chart.js front
end from ``dewdrop/web/static``. The same JSON endpoints are what Berries can
query later over HTTP — no direct SQLite access needed.

Run:  uvicorn dewdrop.api.main:app --host 0.0.0.0 --port 8003
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..blend import ensemble_forecast, service_bias_curves
from ..db import connect

app = FastAPI(title="DEWDROP", version="0.2.0")

_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "location": config.LOCATION_NAME,
            "actuals": config.ENABLED_ACTUALS, "sources": config.ENABLED_SOURCES}


# ── Dashboard: bias-corrected ensemble for the next N days ───────────────
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


# ── Service comparison table ─────────────────────────────────────────────
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
                 "condition_pct": _r(r["condition_pct"], 1), "n": r["n"]}
                for r in rows
            ]}


# ── Bias curves (per service, mean signed error by horizon) ──────────────
@app.get("/api/bias-curves")
def api_bias_curves(metric: str = "temp_high_err", source: str | None = None) -> dict:
    allowed = {"temp_high_err", "temp_low_err", "precip_err"}
    if metric not in allowed:
        metric = "temp_high_err"
    with connect() as conn:
        curves = service_bias_curves(conn, err_col=metric, actuals_source=source)
    return {"metric": metric, "curves": curves}


# ── Daily drill-down: every service at every horizon vs. actual ──────────
@app.get("/api/daily/{target_date}")
def api_daily(target_date: str) -> dict:
    with connect() as conn:
        forecasts = conn.execute(
            """
            SELECT service, horizon_days, fetched_on,
                   temp_high_f, temp_low_f, precip_mm, condition
            FROM forecasts WHERE target_date = ?
            ORDER BY service, horizon_days DESC
            """,
            (target_date,),
        ).fetchall()
        actuals = conn.execute(
            """
            SELECT source, temp_high_f, temp_low_f, precip_mm, condition
            FROM actuals WHERE date = ?
            """,
            (target_date,),
        ).fetchall()
    return {"target_date": target_date,
            "forecasts": [dict(r) for r in forecasts],
            "actuals": [dict(r) for r in actuals]}


# ── Raw log (debug view) ─────────────────────────────────────────────────
@app.get("/api/errors")
def api_errors(limit: int = 200) -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, service, target_date, horizon_days, actuals_source,
                   temp_high_err, temp_low_err, precip_err, condition_match
            FROM forecast_errors
            ORDER BY id DESC LIMIT ?
            """,
            (min(limit, 2000),),
        ).fetchall()
    return {"count": len(rows), "errors": [dict(r) for r in rows]}


# ── Frontend ─────────────────────────────────────────────────────────────
@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
