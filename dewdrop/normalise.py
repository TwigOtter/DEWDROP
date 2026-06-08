"""Condition-label normalisation (design doc §6).

Different APIs use wildly different condition vocabularies. Everything is
mapped to the small controlled set in :data:`models.CONDITIONS` before storage
so that ``condition_match`` is a fair, like-for-like comparison.

Two entry points:
  * :func:`normalise_text`  — free-text labels (NWS, OWM, Weatherbit, ...)
  * :func:`from_wmo_code`   — WMO weather codes (Open-Meteo, ECMWF, ...)
"""
from __future__ import annotations

from . import models

# Substring -> normalised label. Order matters: the first phrase found in the
# (lower-cased) provider text wins, so list the most specific phrases first.
_TEXT_RULES: tuple[tuple[str, str], ...] = (
    # heavy / convective first (so "heavy rain" doesn't match plain "rain")
    ("heavy rain", models.HEAVY_RAIN),
    ("thunder", models.HEAVY_RAIN),
    ("tstorm", models.HEAVY_RAIN),
    ("storm", models.HEAVY_RAIN),
    ("severe", models.HEAVY_RAIN),
    # frozen
    ("snow", models.SNOW),
    ("flurr", models.SNOW),
    ("sleet", models.SNOW),
    ("wintry", models.SNOW),
    ("ice", models.SNOW),
    ("blizzard", models.SNOW),
    # liquid
    ("drizzle", models.RAIN),
    ("shower", models.RAIN),
    ("rain", models.RAIN),
    # obscuration
    ("fog", models.FOG),
    ("mist", models.FOG),
    ("haze", models.FOG),
    ("smoke", models.FOG),
    # cloud cover
    ("partly", models.PARTLY_CLOUDY),
    ("mostly sunny", models.PARTLY_CLOUDY),
    ("scattered cloud", models.PARTLY_CLOUDY),
    ("intermittent", models.PARTLY_CLOUDY),
    ("overcast", models.CLOUDY),
    ("mostly cloudy", models.CLOUDY),
    ("cloud", models.CLOUDY),
    # clear last (it's the weakest signal)
    ("sunny", models.CLEAR),
    ("clear", models.CLEAR),
    ("fair", models.CLEAR),
)


def normalise_text(text: str | None) -> str | None:
    """Map a provider's free-text condition onto a controlled label.

    Returns ``None`` if there's no text or nothing matches (better an explicit
    unknown than a wrong guess).
    """
    if not text:
        return None
    low = text.lower()
    for phrase, label in _TEXT_RULES:
        if phrase in low:
            return label
    return None


# WMO 4677 weather code -> normalised label. Used by Open-Meteo and any other
# source that reports standard WMO codes. Ranges collapsed to the §6 set.
def from_wmo_code(code: int | float | None) -> str | None:
    if code is None:
        return None
    c = int(code)
    if c == 0:
        return models.CLEAR
    if c in (1, 2):
        return models.PARTLY_CLOUDY
    if c == 3:
        return models.CLOUDY
    if c in (45, 48):
        return models.FOG
    if c in (51, 53, 55, 56, 57, 61, 63, 80, 81):  # drizzle + light/mod rain
        return models.RAIN
    if c in (65, 66, 67, 82, 95, 96, 99):           # heavy rain + thunderstorm
        return models.HEAVY_RAIN
    if c in (71, 73, 75, 77, 85, 86):               # snow
        return models.SNOW
    return None
