"""End-to-end smoke test of DB -> scoring -> ensemble (no network)."""
from datetime import date, datetime, timezone
from statistics import fmean

from dewdrop import models
from dewdrop.blend import ensemble_forecast, service_bias_curves
from dewdrop.blend.blender import _winsorize
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
    # Three scored days back this horizon's correction.
    assert by_date[future.isoformat()]["history_days"] == 3


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


def test_precip_hit_categorical(tmp_path):
    db = tmp_path / "t.sqlite3"
    init_db(db)
    with connect(db) as conn:
        insert_forecasts(conn, [
            # Called rain on a rain day (amount off, category right).
            ForecastDay("open_meteo", FETCHED, TARGET, precip_mm=5.0),
            # Called dry on a rain day.
            ForecastDay("nws", FETCHED, TARGET, precip_mm=0.0),
        ])
        insert_actuals(conn, [ActualDay(TARGET, "asos_mci", precip_mm=3.0)])
        assert score_pending(conn) == 2
        hits = {r["service"]: r["precip_hit"] for r in
                conn.execute("SELECT service, precip_hit FROM forecast_errors")}
    assert hits["open_meteo"] == 1
    assert hits["nws"] == 0


def test_condition_derived_for_unlabelled_actuals(tmp_path):
    db = tmp_path / "t.sqlite3"
    init_db(db)
    d_rain, d_heavy, d_snow, d_clear = (date(2026, 6, 2), date(2026, 6, 3),
                                        date(2026, 1, 10), date(2026, 6, 5))
    with connect(db) as conn:
        insert_forecasts(conn, [
            ForecastDay("nws", date(2026, 6, 1), d_rain, condition=models.RAIN),
            ForecastDay("nws", date(2026, 6, 2), d_heavy, condition=models.RAIN),
            ForecastDay("nws", date(2026, 1, 9), d_snow, condition=models.SNOW),
            ForecastDay("nws", date(2026, 6, 4), d_clear, condition=models.CLEAR),
        ])
        insert_actuals(conn, [  # ASOS rows: condition always starts NULL
            ActualDay(d_rain, "asos_mci", temp_high_f=70.0, precip_mm=5.0),
            ActualDay(d_heavy, "asos_mci", temp_high_f=70.0, precip_mm=25.0),
            ActualDay(d_snow, "asos_mci", temp_high_f=28.0, precip_mm=5.0),
            ActualDay(d_clear, "asos_mci", temp_high_f=85.0, precip_mm=0.0),
        ])
        # Bright station day backs the "clear" call on the dry date.
        conn.execute(
            "INSERT INTO station_daily (date, solar_max_wm2) VALUES (?, ?)",
            (d_clear.isoformat(), 700.0),
        )
        assert score_pending(conn) == 4
        conds = {r["date"]: r["condition"] for r in
                 conn.execute("SELECT date, condition FROM actuals")}
        matches = {r["target_date"]: r["condition_match"] for r in
                   conn.execute("SELECT target_date, condition_match "
                                "FROM forecast_errors")}
    assert conds[d_rain.isoformat()] == models.RAIN
    assert conds[d_heavy.isoformat()] == models.HEAVY_RAIN
    assert conds[d_snow.isoformat()] == models.SNOW
    assert conds[d_clear.isoformat()] == models.CLEAR
    assert matches[d_rain.isoformat()] == 1
    assert matches[d_heavy.isoformat()] == 0   # forecast said plain rain
    assert matches[d_clear.isoformat()] == 1


def test_winsorize_tames_outliers():
    # Eleven well-behaved +2° errors and one 40° sensor glitch.
    vals = [2.0] * 11 + [40.0]
    clipped = _winsorize(vals)
    assert max(clipped) < 40.0
    assert fmean(clipped) < fmean(vals)
    # Small samples pass through untouched (percentiles would be noise).
    assert _winsorize([2.0, 40.0]) == [2.0, 40.0]


def test_rain_chance_weights_by_hit_rate(tmp_path):
    db = tmp_path / "t.sqlite3"
    init_db(db)
    future = date(2026, 6, 6)
    with connect(db) as conn:
        insert_forecasts(conn, [
            ForecastDay("open_meteo", date(2026, 6, 5), future, precip_mm=2.0),
            ForecastDay("nws", date(2026, 6, 5), future, precip_mm=0.0),
        ])
        # No history yet: both services count as a coin flip -> 50%.
        days = ensemble_forecast(conn, actuals_source="asos_mci",
                                 now=datetime(2026, 6, 5, 12, tzinfo=timezone.utc))
        day = {d["target_date"]: d for d in days}[future.isoformat()]
        assert day["rain_chance_pct"] == 50

        # Three rainy days: open_meteo called every one, nws missed every one.
        for n in range(3):
            fetched = date(2026, 6, 1 + n)
            target = date(2026, 6, 2 + n)
            insert_forecasts(conn, [
                ForecastDay("open_meteo", fetched, target, precip_mm=4.0),
                ForecastDay("nws", fetched, target, precip_mm=0.0),
            ])
            insert_actuals(conn, [ActualDay(target, "asos_mci", precip_mm=4.0)])
        assert score_pending(conn) == 6

        days = ensemble_forecast(conn, actuals_source="asos_mci",
                                 now=datetime(2026, 6, 5, 12, tzinfo=timezone.utc))
    day = {d["target_date"]: d for d in days}[future.isoformat()]
    # open_meteo (hit rate 1.0) says rain, nws (hit rate 0.0) gets no vote.
    assert day["rain_chance_pct"] == 100


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
