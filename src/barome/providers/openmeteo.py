"""Open-Meteo - FALLBACK 1, worldwide, keyless.

One request returns `pressure_msl`, `surface_pressure` and the grid elevation.
Because Open-Meteo also serves the elevation API, it covers both halves of the
fallback in one dependency with no key and no ToS friction, which is what makes
it the first fallback for everyone rather than a US-only one.

Open-Meteo is a model grid, not a station. It therefore reports no station id
and no distance: the trace should not invent a station that does not exist.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..errors import ProviderError
from ..models import Observation, Station
from ..net import HttpError, build_url, get_json
from ..physics import PA_PER_HPA, PA_PER_INHG

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def hpa_to_inhg(hpa: float) -> float:
    return hpa * PA_PER_HPA / PA_PER_INHG


class OpenMeteoProvider:
    name = "openmeteo"

    def fetch(self, lat: float, lon: float) -> Observation:
        url = build_url(
            FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "current": "pressure_msl,surface_pressure,temperature_2m",
                "timezone": "UTC",
            },
        )
        try:
            data = get_json(url)
        except HttpError as exc:
            raise ProviderError(f"Open-Meteo request failed: {exc}") from exc

        current = data.get("current") or {}
        msl_hpa = current.get("pressure_msl")
        if msl_hpa is None:
            raise ProviderError("Open-Meteo returned no pressure_msl for that point.")

        stamp = current.get("time")
        when = (
            datetime.fromisoformat(stamp).replace(tzinfo=UTC)
            if stamp
            else datetime.now(UTC)
        )
        grid_elev_m = data.get("elevation")

        station = Station(
            id=None,
            name="model grid cell",
            lat=data.get("latitude"),
            lon=data.get("longitude"),
            distance_mi=None,
            # The grid's own elevation, shown for comparison only - like a
            # station elevation, it is never used in the correction.
            elev_ft=float(grid_elev_m) * 3.280839895013123 if grid_elev_m is not None else None,
        )
        return Observation(
            provider=self.name,
            pressure_msl_inhg=hpa_to_inhg(float(msl_hpa)),
            obs_time_utc=when,
            station=station,
            quality=None,
            url=url,
            verify_url=url,
            note=(
                "Open-Meteo is a weather model grid, not a station, so there is no "
                "station id or distance to report."
            ),
            warnings=(),
        )
