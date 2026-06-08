"""Forecast sources. Each implements `ForecastSource` and is registered here."""
from __future__ import annotations

from .base import ForecastSource
from .open_meteo import OpenMeteoSource
from .nws import NWSSource
from .openweathermap import OpenWeatherMapSource
from .tomorrow_io import TomorrowIoSource
from .weatherbit import WeatherbitSource
from .wunderground import WundergroundSource

# Registry keyed by the short name used in DEWDROP_ENABLED_SOURCES.
REGISTRY: dict[str, type[ForecastSource]] = {
    OpenMeteoSource.name: OpenMeteoSource,
    NWSSource.name: NWSSource,
    OpenWeatherMapSource.name: OpenWeatherMapSource,
    TomorrowIoSource.name: TomorrowIoSource,
    WeatherbitSource.name: WeatherbitSource,
    WundergroundSource.name: WundergroundSource,
}


def get_enabled(names: list[str]) -> list[ForecastSource]:
    out: list[ForecastSource] = []
    for n in names:
        cls = REGISTRY.get(n)
        if cls is None:
            raise KeyError(f"Unknown source '{n}'. Known: {sorted(REGISTRY)}")
        out.append(cls())
    return out
