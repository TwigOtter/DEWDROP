"""Parse GW2000X /get_livedata_info JSON into a StationReading.

EcoWitt's livedata payload has four sections we care about:

- ``common_list`` — outdoor sensors keyed by hex ID (``0x02`` outdoor temp, etc.)
- ``wh25`` — single console block: indoor temp/humidity + barometric pressure
- ``piezoRain`` — rain buckets keyed by hex ID (``0x10`` day, ``0x11`` week, ...)
- ``debug`` — uptime / heap; ignored

Values often have units baked into the string (``"73%"``, ``"0.00 mph"``,
``"28.81 inHg"``), so we strip them with a regex before unit conversion.
Output is always normalised to °F, mph, inHg, and mm.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..models import StationReading

# EcoWitt common_list IDs → (StationReading field, conversion kind).
# "kind" picks the converter; "int" coerces the final value to int.
_COMMON_MAP: dict[str, tuple[str, str]] = {
    "0x02": ("temp_out_f",     "temp"),
    "0x07": ("humidity_out",   "int"),
    "0x0A": ("wind_dir_deg",   "int"),
    "0x0B": ("wind_speed_mph", "wind"),
    "0x0C": ("wind_gust_mph",  "wind"),
    "0x15": ("solar_rad_wm2",  "float"),
    "0x17": ("uv_index",       "float"),
}

# EcoWitt piezoRain IDs → field. The accumulators run
# 0x0D=event, 0x0E=rate, 0x10=day, 0x11=week, 0x12=month, 0x13=year.
# We store the daily bucket (resets at local midnight) as precip_daily_mm.
# There is no hourly accumulator in this payload, so precip_hourly_mm is
# left unset rather than mapped to the wrong (non-resetting) bucket.
_RAIN_MAP: dict[str, str] = {
    "0x10": "precip_daily_mm",
}

_NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")


def _split_val(raw: Any, unit_field: str | None) -> tuple[float | None, str]:
    """Pull a number out of a raw EcoWitt val, returning ``(value, unit)``.

    The ``unit`` field on the entry takes precedence; if it's empty we fall
    back to whatever trails the number in the val itself (e.g. ``"73%"`` →
    unit ``"%"``).
    """
    if raw is None:
        return None, unit_field or ""
    s = str(raw).strip()
    m = _NUMERIC.search(s)
    if not m:
        return None, unit_field or ""
    try:
        val = float(m.group())
    except ValueError:
        return None, unit_field or ""
    inline = s[m.end():].strip()
    return val, (unit_field or "").strip() or inline


def _to_f(v: float, unit: str) -> float:
    u = unit.lower()
    if ("°c" in u or u.strip() == "c") and "f" not in u:
        return v * 9 / 5 + 32
    return v


def _to_mph(v: float, unit: str) -> float:
    u = unit.lower()
    if "km" in u:
        return v / 1.60934
    if "m/s" in u:
        return v * 2.23694
    return v


def _to_inhg(v: float, unit: str) -> float:
    u = unit.lower()
    if "hpa" in u or "mb" in u:
        return v / 33.8639
    return v


def _to_mm(v: float, unit: str) -> float:
    u = unit.lower()
    if '"' in u or ("in" in u and "index" not in u):
        return v * 25.4
    return v


def _assign(reading: StationReading, field: str, kind: str, val: float, unit: str) -> None:
    if kind == "temp":
        val = _to_f(val, unit)
    elif kind == "wind":
        val = _to_mph(val, unit)
    elif kind == "pressure":
        val = _to_inhg(val, unit)
    elif kind == "rain":
        val = _to_mm(val, unit)
    setattr(reading, field, int(round(val)) if kind == "int" else round(val, 2))


def parse(data: dict[str, Any]) -> StationReading:
    """Parse a GW2000X /get_livedata_info payload into a StationReading.

    Values are normalised to °F, mph, inHg, and mm. Unknown sensor IDs and
    missing sections are silently ignored; the resulting reading carries
    ``None`` for any field the device didn't report.
    """
    reading = StationReading(
        ts=datetime.now(timezone.utc),
        raw_json=json.dumps(data),
    )

    for entry in data.get("common_list", []) or []:
        cfg = _COMMON_MAP.get(str(entry.get("id", "")))
        if not cfg:
            continue
        field, kind = cfg
        val, unit = _split_val(entry.get("val"), entry.get("unit"))
        if val is not None:
            _assign(reading, field, kind, val, unit)

    for entry in data.get("piezoRain", []) or []:
        field = _RAIN_MAP.get(str(entry.get("id", "")))
        if not field:
            continue
        val, unit = _split_val(entry.get("val"), entry.get("unit"))
        if val is not None:
            _assign(reading, field, "rain", val, unit)

    # wh25 is a single console block, not an array of typed sensors. Its
    # ``unit`` applies to the temp fields only; humidity and pressure carry
    # their units inline.
    for block in data.get("wh25", []) or []:
        temp_unit = block.get("unit", "")
        intemp, _u = _split_val(block.get("intemp"), temp_unit)
        if intemp is not None:
            reading.temp_in_f = round(_to_f(intemp, temp_unit), 2)
        inhumi, _u = _split_val(block.get("inhumi"), None)
        if inhumi is not None:
            reading.humidity_in = int(round(inhumi))
        # Prefer relative (sea-level adjusted) pressure; fall back to absolute.
        for key in ("rel", "abs"):
            press, press_u = _split_val(block.get(key), None)
            if press is not None:
                reading.pressure_inhg = round(_to_inhg(press, press_u), 2)
                break

    return reading


_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def wind_dir_label(deg: int | None) -> str:
    if deg is None:
        return "—"
    return _COMPASS[round(deg / 45) % 8]
