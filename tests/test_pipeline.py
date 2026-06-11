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

    # Three scored days of horizon-1 history (enough to clear the
    # MIN_BIAS_SAMPLES guard): open_meteo runs 1° cold, nws 3° hot.
    with connect(db) as conn:
        for n in range(3):
            fetched = date(2026, 6, 1 + n)
            target = date(2026, 6, 2 + n)
            insert_forecasts(conn, [
                ForecastDay("open_meteo", fetched, target, temp_high_f=70.0,
                            temp_low_f=50.0, precip_mm=0.0, wind_max_mph=10.0,
                            condition=models.CLEAR),
                ForecastDay("nws", fetched, target, temp_high_f=74.0,
                            temp_low_f=52.0, precip_mm=1.0, wind_max_mph=14.0,
                            condition=models.CLOUDY),
            ])
            insert_actuals(conn, [
                ActualDay(target, "asos_mci", temp_high_f=71.0, temp_low_f=50.0,
                          precip_mm=0.0, wind_max_mph=12.0,
                          condition=models.CLEAR),
                # Secondary station actuals must stay out of the error history.
                ActualDay(target, "gw2000_local", temp_high_f=73.0,
                          temp_low_f=52.0),
            ])
        # A snapshot taken *after* its target day (negative horizon) is never
        # scored.
        insert_forecasts(conn, [
            ForecastDay("nws", date(2026, 6, 3), date(2026, 6, 2),
                        temp_high_f=72.0),
        ])

    # Horizon is derived from the two dates.
    with connect(db) as conn:
        h = conn.execute(
            "SELECT horizon_days FROM forecasts "
            "WHERE service='nws' AND fetched_on='2026-06-01'").fetchone()
        assert h["horizon_days"] == 1

    # Score: 2 services x 3 days, only against the primary ground truth.
    with connect(db) as conn:
        assert score_pending(conn) == 6

    with connect(db) as conn:
        stray = conn.execute(
            "SELECT COUNT(*) AS n FROM forecast_errors "
            "WHERE actuals_source != 'asos_mci' OR horizon_days < 0"
        ).fetchone()["n"]
        assert stray == 0
        rows = {r["service"]: r for r in
                conn.execute("SELECT service, temp_high_err, wind_err, "
                             "condition_match FROM forecast_errors")}
    assert rows["open_meteo"]["temp_high_err"] == -1.0   # 70 - 71
    assert rows["nws"]["temp_high_err"] == 3.0           # 74 - 71
    assert rows["open_meteo"]["wind_err"] == -2.0        # 10 - 12
    assert rows["nws"]["wind_err"] == 2.0                # 14 - 12
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
    future = date(2026, 6, 6)
    with connect(db) as conn:
        insert_forecasts(conn, [
            ForecastDay("open_meteo", date(2026, 6, 5), future,
                        temp_high_f=80.0, wind_max_mph=20.0),
            ForecastDay("nws", date(2026, 6, 5), future,
                        temp_high_f=84.0, wind_max_mph=24.0),
        ])
        days = ensemble_forecast(conn, actuals_source="asos_mci",
                                 now=datetime(2026, 6, 5, 12, tzinfo=timezone.utc))

    by_date = {d["target_date"]: d for d in days}
    # open_meteo (bias -1 -> 81) and nws (bias +3 -> 81) both correct to 81.
    assert by_date[future.isoformat()]["temp_high_f"] == 81.0
    # Wind blends the same way: 20-(-2) and 24-2 both correct to 22.
    assert by_date[future.isoformat()]["wind_max_mph"] == 22.0


def test_bias_not_applied_below_min_samples(tmp_path):
    db = tmp_path / "t.sqlite3"
    init_db(db)
    # One scored day: a +5° bias exists but is below MIN_BIAS_SAMPLES.
    with connect(db) as conn:
        insert_forecasts(conn, [
            ForecastDay("nws", FETCHED, TARGET, temp_high_f=76.0),
        ])
        insert_actuals(conn, [
            ActualDay(TARGET, "asos_mci", temp_high_f=71.0),
        ])
        assert score_pending(conn) == 1

        future = date(2026, 6, 4)
        insert_forecasts(conn, [
            ForecastDay("nws", date(2026, 6, 3), future, temp_high_f=80.0),
        ])
        days = ensemble_forecast(conn, actuals_source="asos_mci",
                                 now=datetime(2026, 6, 3, 12, tzinfo=timezone.utc))
    day = {d["target_date"]: d for d in days}[future.isoformat()]
    assert day["temp_high_f"] == 80.0  # uncorrected — not 75


def test_ensemble_precip_never_negative(tmp_path):
    db = tmp_path / "t.sqlite3"
    init_db(db)
    with connect(db) as conn:
        # Three days where the service over-forecast precip by 8 mm.
        for n in range(3):
            fetched = date(2026, 6, 1 + n)
            target = date(2026, 6, 2 + n)
            insert_forecasts(conn, [
                ForecastDay("open_meteo", fetched, target, precip_mm=8.0),
            ])
            insert_actuals(conn, [
                ActualDay(target, "asos_mci", precip_mm=0.0),
            ])
        assert score_pending(conn) == 3

        # A 2 mm forecast minus an 8 mm bias would be -6 mm; clamp to 0.
        future = date(2026, 6, 6)
        insert_forecasts(conn, [
            ForecastDay("open_meteo", date(2026, 6, 5), future, precip_mm=2.0),
        ])
        days = ensemble_forecast(conn, actuals_source="asos_mci",
                                 now=datetime(2026, 6, 5, 12, tzinfo=timezone.utc))
    day = {d["target_date"]: d for d in days}[future.isoformat()]
    assert day["precip_mm"] == 0.0


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
