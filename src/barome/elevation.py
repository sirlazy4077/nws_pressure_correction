"""lat/lon -> the elevation at *that point*, which is the user's address.

Not the weather station's elevation. The station-vs-address gap measured at the
test point was 55 ft (~0.18% in Ctp), which is four times larger than the total
disagreement between every elevation dataset available (13.1 ft, ~0.044%).
Fixing *which point* we ask about is what matters; which service answers does
not, which is why the chain simply takes the first that responds.
"""

from __future__ import annotations

from functools import lru_cache

from .config import ELEVATION_CHAIN, USGS_TIMEOUT_S
from .errors import ElevationError
from .net import HttpError, build_url, get_json
from .physics import FT_PER_M

USGS_URL = "https://epqs.nationalmap.gov/v1/json"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/elevation"
OPENTOPO_URL = "https://api.opentopodata.org/v1"

# USGS returns this for points outside its DEM. Treating it as a miss is what
# lets the chain work for non-US addresses without a country check.
USGS_OFF_GRID = -1000000.0

ELEVATION_SOURCE_LABEL = {
    "usgs": "USGS EPQS (NED, 1 m)",
    "openmeteo": "Open-Meteo (Copernicus GLO-90)",
    "opentopodata-ned10m": "OpenTopoData (NED, 10 m)",
    "opentopodata-srtm30m": "OpenTopoData (SRTM, 30 m)",
}


def _usgs(lat: float, lon: float) -> tuple[float, str, str] | None:
    url = build_url(USGS_URL, {"x": lon, "y": lat, "units": "Feet", "wkid": 4326,
                               "includeDate": "false"})
    try:
        data = get_json(url, timeout=USGS_TIMEOUT_S)
    except HttpError:
        return None
    value = data.get("value")
    if value is None:
        return None
    try:
        feet = float(value)
    except (TypeError, ValueError):
        return None
    if feet <= USGS_OFF_GRID:
        return None
    return feet, "usgs", url


def _openmeteo(lat: float, lon: float) -> tuple[float, str, str] | None:
    url = build_url(OPEN_METEO_URL, {"latitude": lat, "longitude": lon})
    try:
        data = get_json(url)
    except HttpError:
        return None
    values = data.get("elevation") or []
    if not values:
        return None
    return float(values[0]) * FT_PER_M, "openmeteo", url


def _opentopodata(lat: float, lon: float) -> tuple[float, str, str] | None:
    # ned10m is US-only and better where it exists; srtm30m covers the world.
    for dataset in ("ned10m", "srtm30m"):
        url = build_url(f"{OPENTOPO_URL}/{dataset}", {"locations": f"{lat},{lon}"})
        try:
            data = get_json(url)
        except HttpError:
            continue
        results = data.get("results") or []
        if not results:
            continue
        metres = results[0].get("elevation")
        if metres is None:
            continue
        return float(metres) * FT_PER_M, f"opentopodata-{dataset}", url
    return None


_SOURCES = {"usgs": _usgs, "openmeteo": _openmeteo, "opentopodata": _opentopodata}


@lru_cache(maxsize=256)
def _cached(lat_r: float, lon_r: float, chain: tuple[str, ...]):
    problems: list[str] = []
    for name in chain:
        func = _SOURCES.get(name)
        if func is None:
            continue
        hit = func(lat_r, lon_r)
        if hit is not None:
            return hit
        problems.append(name)
    raise ElevationError(
        "Could not determine the elevation for "
        f"{lat_r}, {lon_r} (tried {', '.join(problems) or 'nothing'})."
    )


def elevation_ft(
    lat: float,
    lon: float,
    chain: tuple[str, ...] = ELEVATION_CHAIN,
) -> tuple[float, str, str]:
    """Returns (feet, source_key, url).

    Cached on coordinates rounded to 4 dp (~11 m): a clinic re-checks the same
    address all day and its elevation does not change. This also keeps
    Nominatim's rate policy comfortably satisfied upstream.
    """
    return _cached(round(float(lat), 4), round(float(lon), 4), tuple(chain))


def source_label(key: str) -> str:
    return ELEVATION_SOURCE_LABEL.get(key, key)
