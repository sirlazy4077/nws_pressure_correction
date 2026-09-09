"""NWS / api.weather.gov - FALLBACK 2, US only, keyless.

**The trap this provider exists to get right.** The field named
`barometricPressure` is *not* station pressure despite its name - it is the
altimeter setting, i.e. already sea-level adjusted. Verified against
high-elevation stations, where the two cannot be confused:

    KLXV (Leadville, 3026 m) reports barometricPressure = 1037.93 hPa.
    Read as a station reading it implies an MSL of 1505 hPa - impossible, +47%.
    Read correctly as an altimeter setting it implies a station pressure of
    715.8 hPa, which is right for 3000 m.

A sea-level-only test would never have caught this. So this provider returns
that value as P_msl, exactly like every other provider, and lets physics.py do
the one correction.

Two further facts shape the implementation:
  * `seaLevelPressure` was null at every station tested (qualityControl "Z"),
    so it cannot be relied on.
  * KDEN returned no `barometricPressure` at all, so null readings are normal
    and the provider must walk down the station list rather than trusting the
    first entry.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..config import MAX_STATIONS_TO_TRY
from ..errors import ProviderError
from ..models import Observation, Station
from ..net import HttpError, get_json
from ..physics import FT_PER_M, PA_PER_INHG, haversine_mi

POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
HEADERS = {"Accept": "application/geo+json"}


def pa_to_inhg(pa: float) -> float:
    return pa / PA_PER_INHG


def _station_list(lat: float, lon: float) -> tuple[list[dict], str]:
    points_url = POINTS_URL.format(lat=round(lat, 4), lon=round(lon, 4))
    try:
        point = get_json(points_url, headers=HEADERS)
    except HttpError as exc:
        raise ProviderError(
            f"NWS does not cover that point, or is unavailable: {exc}"
        ) from exc

    stations_url = (point.get("properties") or {}).get("observationStations")
    if not stations_url:
        raise ProviderError("NWS returned no observation stations for that point.")
    try:
        listing = get_json(stations_url, headers=HEADERS)
    except HttpError as exc:
        raise ProviderError(f"NWS station list unavailable: {exc}") from exc

    out: list[dict] = []
    for feature in listing.get("features") or []:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
        elev_m = (props.get("elevation") or {}).get("value")
        s_lat, s_lon = coords[1], coords[0]
        out.append(
            {
                "id": props.get("stationIdentifier"),
                "name": props.get("name"),
                "lat": s_lat,
                "lon": s_lon,
                "distance_mi": (
                    haversine_mi(lat, lon, float(s_lat), float(s_lon))
                    if s_lat is not None and s_lon is not None
                    else None
                ),
                "elev_ft": float(elev_m) * FT_PER_M if elev_m is not None else None,
            }
        )
    if not out:
        raise ProviderError("NWS returned an empty station list for that point.")
    return out, stations_url


class NwsProvider:
    name = "nws"
    us_only = True

    def fetch(self, lat: float, lon: float) -> Observation:
        stations, listing_url = _station_list(lat, lon)
        problems: list[str] = []

        for candidate in stations[:MAX_STATIONS_TO_TRY]:
            sid = candidate["id"]
            if not sid:
                continue
            url = f"https://api.weather.gov/stations/{sid}/observations/latest"
            try:
                data = get_json(url, headers=HEADERS)
            except HttpError as exc:
                problems.append(f"{sid}: {exc}")
                continue

            props = data.get("properties") or {}
            baro = props.get("barometricPressure") or {}
            value_pa = baro.get("value")
            if value_pa is None:
                # Normal - KDEN does this. Keep walking.
                problems.append(f"{sid}: barometricPressure was null")
                continue

            qc = baro.get("qualityControl")
            warnings: list[str] = []
            if qc and qc not in {"V", "C", "S"}:
                warnings.append(
                    f"NWS station {sid} reported quality control flag {qc!r} rather than "
                    "'V' (validated). Treat this reading with care."
                )

            stamp = props.get("timestamp")
            when = (
                datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if stamp
                else datetime.now(UTC)
            )

            station = Station(
                id=sid,
                name=candidate.get("name"),
                lat=candidate.get("lat"),
                lon=candidate.get("lon"),
                distance_mi=candidate.get("distance_mi"),
                elev_ft=candidate.get("elev_ft"),
            )
            return Observation(
                provider=self.name,
                pressure_msl_inhg=pa_to_inhg(float(value_pa)),
                obs_time_utc=when,
                station=station,
                quality=f"qualityControl {qc}" if qc else None,
                url=url,
                verify_url=f"https://www.weather.gov/wrh/timeseries?site={sid}",
                note=(
                    "NWS 'barometricPressure' is the altimeter setting, i.e. already "
                    "sea-level adjusted, despite its name. Read as such here."
                ),
                warnings=tuple(warnings),
            )

        raise ProviderError(
            "No NWS station near that point reported a barometric pressure. "
            + "; ".join(problems)
            + f" (station list: {listing_url})"
        )
