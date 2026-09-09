"""Pressure providers. All three ship together.

The primary route depends on a public key that can rotate or be rate-limited
without notice, so the fallbacks are not a nice-to-have: they are what keeps
the tool working on the day the key stops.
"""

from __future__ import annotations

from .base import PressureProvider, us_only
from .nws import NwsProvider
from .openmeteo import OpenMeteoProvider
from .wunderground import WundergroundProvider

PROVIDERS: dict[str, type] = {
    "wunderground": WundergroundProvider,
    "openmeteo": OpenMeteoProvider,
    "nws": NwsProvider,
}

PROVIDER_LABEL = {
    "wunderground": "Weather Underground",
    "openmeteo": "Open-Meteo",
    "nws": "NWS (api.weather.gov)",
}


def get_provider(name: str) -> PressureProvider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise ValueError(
            f"Unknown provider {name!r}. Choose from: {', '.join(PROVIDERS)}"
        ) from None


def label(name: str) -> str:
    return PROVIDER_LABEL.get(name, name)


__all__ = [
    "PROVIDERS",
    "PressureProvider",
    "get_provider",
    "label",
    "us_only",
    "NwsProvider",
    "OpenMeteoProvider",
    "WundergroundProvider",
]
