"""Weather Underground personal weather stations - PRIMARY, worldwide.

Two documented JSON endpoints replace the BeautifulSoup selectors the old code
used. Those selectors ("test-false wu-unit wu-unit-pressure ng-star-inserted")
were Angular-generated class names that change on any WU frontend deploy;
`ng-star-inserted` in particular is a runtime artifact, not an API.

WU reports `imperial.pressure` as a **sea-level-adjusted** value: 30.28 inHg at
a 380 ft station is only plausible as an altimeter setting.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..config import MAX_STATIONS_TO_TRY, wu_api_key
from ..errors import ProviderError
from ..models import Observation, Station
from ..net import HttpError, build_url, get_json
from ..physics import haversine_mi

NEAR_URL = "https://api.weather.com/v3/location/near"
OBS_URL = "https://api.weather.com/v2/pws/observations/current"

QC_MEANING = {
    1: "passed",
    0: "not checked",
    -1: "failed",
}


def _stations_near(lat: float, lon: float) -> tuple[list[dict], str]:
    url = build_url(
        NEAR_URL,
        {
            "geocode": f"{lat},{lon}",
            "product": "pws",
            "format": "json",
            "apiKey": wu_api_key(),
        },
    )
    try:
        data = get_json(url)
    except HttpError as exc:
        raise ProviderError(f"Weather Underground station lookup failed: {exc}") from exc

    loc = data.get("location") or {}
    ids = loc.get("stationId") or []
    if not ids:
        raise ProviderError("Weather Underground returned no stations near that point.")

    names = loc.get("stationName") or []
    lats = loc.get("latitude") or []
    lons = loc.get("longitude") or []
    dist_km = loc.get("distanceKm") or []
    qc = loc.get("qcStatus") or []

    out: list[dict] = []
    for i, sid in enumerate(ids):
        s_lat = lats[i] if i < len(lats) else None
        s_lon = lons[i] if i < len(lons) else None
        if i < len(dist_km) and dist_km[i] is not None:
            miles = float(dist_km[i]) * 0.621371
        elif s_lat is not None and s_lon is not None:
            miles = haversine_mi(lat, lon, float(s_lat), float(s_lon))
        else:
            miles = None
        out.append(
            {
                "id": sid,
                "name": names[i] if i < len(names) else None,
                "lat": s_lat,
                "lon": s_lon,
                "distance_mi": miles,
                "qc": qc[i] if i < len(qc) else None,
            }
        )
    return out, url


def _observation(station_id: str) -> tuple[dict, str]:
    url = build_url(
        OBS_URL,
        {"stationId": station_id, "format": "json", "units": "e", "apiKey": wu_api_key()},
    )
    data = get_json(url)
    obs = (data.get("observations") or [None])[0]
    if not obs:
        raise HttpError(f"no current observation for {station_id}")
    return obs, url


class WundergroundProvider:
    name = "wunderground"

    def fetch(self, lat: float, lon: float) -> Observation:
        stations, near_url = _stations_near(lat, lon)
        problems: list[str] = []

        # Walk down the list: a personal weather station can be online but
        # reporting nothing useful, which is normal and must not be fatal.
        for candidate in stations[:MAX_STATIONS_TO_TRY]:
            sid = candidate["id"]
            try:
                obs, obs_url = _observation(sid)
            except HttpError as exc:
                problems.append(f"{sid}: {exc}")
                continue

            imperial = obs.get("imperial") or {}
            pressure = imperial.get("pressure")
            if pressure is None:
                problems.append(f"{sid}: no pressure reported")
                continue

            elev = imperial.get("elev", obs.get("elev"))
            qc_raw = obs.get("qcStatus", candidate.get("qc"))
            quality = None
            if qc_raw is not None:
                quality = f"qcStatus {qc_raw} ({QC_MEANING.get(qc_raw, 'unknown')})"

            warnings: list[str] = []
            if qc_raw == -1:
                warnings.append(
                    f"Weather Underground flagged station {sid} as failing quality control "
                    "(qcStatus -1). Treat this reading with suspicion."
                )

            obs_time = obs.get("obsTimeUtc")
            when = (
                datetime.fromisoformat(obs_time.replace("Z", "+00:00"))
                if obs_time
                else datetime.now(UTC)
            )

            station = Station(
                id=sid,
                name=obs.get("neighborhood") or candidate.get("name"),
                lat=obs.get("lat", candidate.get("lat")),
                lon=obs.get("lon", candidate.get("lon")),
                distance_mi=candidate.get("distance_mi"),
                elev_ft=float(elev) if elev is not None else None,
            )
            return Observation(
                provider=self.name,
                pressure_msl_inhg=float(pressure),
                obs_time_utc=when,
                station=station,
                quality=quality,
                url=obs_url,
                verify_url=f"https://www.wunderground.com/dashboard/pws/{sid}",
                note=f"nearest station of {len(stations)} found via {near_url.split('?')[0]}",
                warnings=tuple(warnings),
            )

        raise ProviderError(
            "No Weather Underground station near that point reported a usable pressure. "
            + "; ".join(problems)
        )
