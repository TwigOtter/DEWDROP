"""Derive a coarse condition label for actuals sources that don't report one.

ASOS daily summaries carry no condition, so ``condition_match`` could never be
scored against the primary ground truth. This derives a label good enough for
the 7-word condition vocabulary:

- Wet days come from the observed precip total (rain / heavy_rain, or snow
  when the day stayed near freezing).
- Dry days are split clear / partly_cloudy / cloudy by comparing the local
  station's peak solar reading against a rough clear-sky maximum for that
  latitude and day of year. No station data -> dry days stay unlabelled.

The clear-sky model is deliberately crude (solar-noon elevation x a fixed
atmospheric factor); it only needs to separate "bright" from "grey" days, not
predict irradiance. Thresholds below were eyeballed for mid-latitudes.
"""
from __future__ import annotations

import math
from datetime import date

from .. import config, models

# Precip (mm) at/above which a day counts as heavy rain.
HEAVY_RAIN_MM = 10.0
# A wet day whose high never exceeded this is called snow, not rain.
SNOW_MAX_TEMP_F = 35.0
# Fraction of the clear-sky max the station's peak solar must reach.
CLEAR_RATIO = 0.65
PARTLY_CLOUDY_RATIO = 0.40


def clear_sky_max_wm2(day: date, lat_deg: float) -> float:
    """Rough clear-sky peak irradiance (W/m²) at solar noon for a date/latitude."""
    doy = day.timetuple().tm_yday
    declination = 23.44 * math.sin(2 * math.pi * (284 + doy) / 365.0)
    elevation = max(min(90.0 - abs(lat_deg - declination), 90.0), 0.0)
    # ~1100 W/m² extraterrestrial-ish peak x ~0.75 atmospheric transmission.
    return 1100.0 * 0.75 * math.sin(math.radians(elevation))


def derive_condition(
    day: date,
    precip_mm: float | None,
    temp_high_f: float | None,
    solar_max_wm2: float | None,
    lat_deg: float | None = None,
) -> str | None:
    """Best-effort condition label from observed daily metrics, or None."""
    if precip_mm is None:
        # Without a precip reading we can't tell cloudy from rain — a low
        # solar peak alone is ambiguous.
        return None
    if precip_mm >= config.RAIN_THRESHOLD_MM:
        if temp_high_f is not None and temp_high_f <= SNOW_MAX_TEMP_F:
            return models.SNOW
        return models.HEAVY_RAIN if precip_mm >= HEAVY_RAIN_MM else models.RAIN

    # Dry day: need a solar reading to grade cloud cover.
    if solar_max_wm2 is None:
        return None
    expected = clear_sky_max_wm2(day, config.LATITUDE if lat_deg is None else lat_deg)
    if expected <= 0:
        return None
    ratio = solar_max_wm2 / expected
    if ratio >= CLEAR_RATIO:
        return models.CLEAR
    if ratio >= PARTLY_CLOUDY_RATIO:
        return models.PARTLY_CLOUDY
    return models.CLOUDY
