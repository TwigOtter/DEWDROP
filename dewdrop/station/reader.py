"""Parse GW2000X /get_livedata_info JSON into a StationReading.

Handles unit conversion so callers always get °F, mph, inHg, and mm
regardless of how the device is configured.

The sensor `name` field varies slightly across firmware versions, so we use
substring matching (most-specific rule first) rather than exact equality.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..models import StationReading

# (name_substring, field, unit_kind)  — first match wins; put specific before general.
_RULES: list[tuple[str, str, str]] = [
    ("outdoor temperature",  "temp_out_f",        "temp"),
    ("outdoor temp",         "temp_out_f",        "temp"),
    ("indoor temperature",   "temp_in_f",         "temp"),
    ("indoor temp",          "temp_in_f",         "temp"),
    ("outdoor humidity",     "humidity_out",      "int"),
    ("indoor humidity",      "humidity_in",       "int"),
    ("absolute pressure",    "pressure_inhg",     "pressure"),
    ("relative pressure",    "pressure_inhg",     "pressure"),
    ("barometric",           "pressure_inhg",     "pressure"),
    ("wind speed",           "wind_speed_mph",    "wind"),
    ("gust speed",           "wind_gust_mph",     "wind"),
    ("wind gust",            "wind_gust_mph",     "wind"),
    ("wind direction",       "wind_dir_deg",      "int"),
    ("wind dir",             "wind_dir_deg",      "int"),
    ("hourly rain",          "precip_hourly_mm",  "rain"),
    ("rain rate",            "precip_hourly_mm",  "rain"),
    ("daily rain",           "precip_daily_mm",   "rain"),
    ("uv index",             "uv_index",          "float"),
    ("solar and uvi",        "solar_rad_wm2",     "float"),
    ("solar radiation",      "solar_rad_wm2",     "float"),
    ("solar",                "solar_rad_wm2",     "float"),
]


def _to_f(v: float, unit: str) -> float:
    u = unit.lower()
    # Convert only when explicitly Celsius; default is Fahrenheit.
    if ("°c" in u or u.strip() == "c") and "f" not in u:
        return v * 9 / 5 + 32
    return v


def _to_mph(v: float, unit: str) -> float:
    u = unit.lower()
    if "km" in u:
        return v / 1.60934
    if "m/s" in u:
        return v * 2.23694
    return v  # assume mph


def _to_inhg(v: float, unit: str) -> float:
    u = unit.lower()
    if "hpa" in u or "mb" in u:
        return v / 33.8639
    return v  # assume inHg


def _to_mm(v: float, unit: str) -> float:
    u = unit.lower()
    if '"' in u or ("in" in u and "index" not in u):
        return v * 25.4
    return v  # assume mm


def parse(data: dict[str, Any]) -> StationReading:
    """Parse a raw /get_livedata_info payload. Returns a StationReading in
    standard units (°F, mph, inHg, mm)."""
    reading = StationReading(
        ts=datetime.now(timezone.utc),
        raw_json=json.dumps(data),
    )
    for sensor in data.get("sensor", []):
        name = sensor.get("name", "").lower()
        try:
            val = float(sensor.get("val", ""))
        except (TypeError, ValueError):
            continue
        unit = str(sensor.get("unit", ""))

        for substr, field, kind in _RULES:
            if substr in name:
                if kind == "temp":
                    val = _to_f(val, unit)
                elif kind == "wind":
                    val = _to_mph(val, unit)
                elif kind == "pressure":
                    val = _to_inhg(val, unit)
                elif kind == "rain":
                    val = _to_mm(val, unit)
                setattr(reading, field,
                        int(round(val)) if kind == "int" else round(val, 2))
                break

    return reading


_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def wind_dir_label(deg: int | None) -> str:
    if deg is None:
        return "—"
    return _COMPASS[round(deg / 45) % 8]
