"""End-to-end smoke test of DB -> scoring -> ensemble (no network)."""
from datetime import date, datetime, timezone

from dewdrop import models
from dewdrop.blend import ensemble_forecast, service_bias_curves
from dewdrop.db import connect, init_db, insert_actuals, insert_forecasts
from dewdrop.models import ActualDay, ForecastDay
from dewdrop.scoring import score_pending

FETCHED = date(2026, 6, 1)
TARGET = date(2026, 6, 2)


def test_score_and_ensemble(tmp_path):
    db = tmp_path / "t.sqlite3"
    init_db(db)

    # Two services predict the same target day at horizon 1; one runs hot.
    with connect(db) as conn:
        insert_forecasts(conn, [
            ForecastDay("open_meteo", FETCHED, TARGET, temp_high_f=70.0,
                        temp_low_f=50.0, precip_mm=0.0, condition=models.CLEAR),
            ForecastDay("nws", FETCHED, TARGET, temp_high_f=74.0,
                        temp_low_f=52.0, precip_mm=1.0, condition=models.CLOUDY),
        ])
        insert_actuals(conn, [
            ActualDay(TARGET, "asos_mci", temp_high_f=71.0, temp_low_f=50.0,
                      precip_mm=0.0, condition=models.CLEAR),
        ])

    # Horizon is derived from the two dates.
    with connect(db) as conn:
        h = conn.execute("SELECT horizon_days FROM forecasts WHERE service='nws'").fetchone()
        assert h["horizon_days"] == 1

    # Score: signed high-temp errors + condition match.
    with connect(db) as conn:
        assert score_pending(conn) == 2

    with connect(db) as conn:
        rows = {r["service"]: r for r in
                conn.execute("SELECT service, temp_high_err, condition_match "
                             "FROM forecast_errors")}
    assert rows["open_meteo"]["temp_high_err"] == -1.0   # 70 - 71
    assert rows["nws"]["temp_high_err"] == 3.0           # 74 - 71
    assert rows["open_meteo"]["condition_match"] == 1     # clear == clear
    assert rows["nws"]["condition_match"] == 0            # cloudy != clear

    # Re-scoring is idempotent.
    with connect(db) as conn:
        assert score_pending(conn) == 0

    # Bias curve reflects the signed errors at horizon 1.
    with connect(db) as conn:
        curves = service_bias_curves(conn, "temp_high_err", "asos_mci")
    assert curves["open_meteo"][0]["mean_err"] == -1.0
    assert curves["nws"][0]["mean_err"] == 3.0

    # A future forecast is bias-corrected toward truth in the ensemble.
    future = date(2026, 6, 3)
    with connect(db) as conn:
        insert_forecasts(conn, [
            ForecastDay("open_meteo", date(2026, 6, 2), future, temp_high_f=80.0),
            ForecastDay("nws", date(2026, 6, 2), future, temp_high_f=84.0),
        ])
        days = ensemble_forecast(conn, actuals_source="asos_mci",
                                 now=datetime(2026, 6, 2, 12, tzinfo=timezone.utc))

    by_date = {d["target_date"]: d for d in days}
    # open_meteo (bias -1 -> 81) and nws (bias +3 -> 81) both correct to ~81.
    assert 80.0 <= by_date[future.isoformat()]["temp_high_f"] <= 82.0


def test_condition_match_null_when_actual_missing(tmp_path):
    db = tmp_path / "t.sqlite3"
    init_db(db)
    with connect(db) as conn:
        insert_forecasts(conn, [
            ForecastDay("nws", FETCHED, TARGET, temp_high_f=70.0, condition=models.RAIN),
        ])
        insert_actuals(conn, [  # ASOS has no condition label
            ActualDay(TARGET, "asos_mci", temp_high_f=68.0, condition=None),
        ])
        assert score_pending(conn) == 1
        row = conn.execute("SELECT condition_match, temp_high_err, precip_err "
                           "FROM forecast_errors").fetchone()
    assert row["condition_match"] is None
    assert row["temp_high_err"] == 2.0
    assert row["precip_err"] is None  # neither side had precip
