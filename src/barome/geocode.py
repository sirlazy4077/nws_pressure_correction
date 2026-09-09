"""Address -> Location, over a chain of free keyless geocoders.

US Census first: for US addresses it gives a true street match with no rate
limit and no usage policy to honour. Nominatim and Photon then provide
worldwide coverage. The first one to return a hit wins, and `Location.source`
records which, so the user can see it.
"""

from __future__ import annotations

import functools
import logging
import threading
from functools import lru_cache

from .config import GEOCODER_CHAIN, USER_AGENT
from .errors import GeocodingError
from .models import Location
from .net import HttpError, build_url, certificate_advice, get_json, ssl_context

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
PHOTON_URL = "https://photon.komoot.io/api/"

# Nominatim's policy is max 1 request/second. geopy's RateLimiter enforces the
# delay per wrapped callable, so the wrappers are built once and reused.
_geopy_lock = threading.Lock()
_geopy_cache: dict[str, object] = {}


def _require_geopy():
    try:
        import geopy.geocoders  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise GeocodingError(
            "geopy is not installed, so only the US Census geocoder is available. "
            "Install it with: pip install geopy"
        ) from exc


def _rate_limited(name: str):
    """Build (once) a rate-limited geocode callable for 'nominatim'/'photon'."""
    with _geopy_lock:
        if name in _geopy_cache:
            return _geopy_cache[name]
        _require_geopy()
        # geopy's RateLimiter dumps a full traceback to the log before each
        # retry. The chain below is already the retry mechanism - a different
        # provider - so keep the console clean and let it fall through.
        logging.getLogger("geopy").setLevel(logging.ERROR)
        from geopy.extra.rate_limiter import RateLimiter  # note: geopy.extra, not .geocoders
        from geopy.geocoders import Nominatim, Photon

        # geopy uses its own HTTP stack, so it needs the same trust decision
        # handed to it explicitly (see net.ssl_context). None means "geopy's
        # default", which is what we want when truststore is not in play.
        context = ssl_context()

        if name == "nominatim":
            coder = Nominatim(user_agent=USER_AGENT, timeout=12, ssl_context=context)
            call = RateLimiter(
                functools.partial(coder.geocode, addressdetails=True),
                min_delay_seconds=1.0,
                max_retries=0,
                swallow_exceptions=False,
            )
        else:
            coder = Photon(user_agent=USER_AGENT, timeout=12, ssl_context=context)
            call = RateLimiter(coder.geocode, min_delay_seconds=1.0, max_retries=0,
                               swallow_exceptions=False)
        _geopy_cache[name] = call
        return call


def _transport_reason(exc: Exception) -> str:
    """Turn a geopy/urllib failure into one line a user can act on."""
    text = str(exc) or exc.__class__.__name__
    if "CERTIFICATE_VERIFY_FAILED" in text or "SSLCertVerification" in text:
        return certificate_advice()
    return f"could not be reached ({text.splitlines()[0][:120]})"


def _norm_cc(value: str | None) -> str | None:
    """Nominatim returns 'us', Photon returns 'US'. Normalise, or every
    Nominatim-resolved US address silently gets the wrong Ctp protocol."""
    if not value:
        return None
    return str(value).strip().upper() or None


# --- Address suggestions --------------------------------------------------
#
# Photon is the only geocoder in the chain that may be used this way.
# Nominatim's usage policy prohibits autocomplete and type-ahead outright, and
# Census has no suggest endpoint - it answers a whole address or nothing.
# Photon is built as a search-as-you-type geocoder, which is exactly this job.
#
# A suggestion is a fully resolved Location, not a string: Photon returns the
# coordinates and country with the candidate. So confirming a suggestion costs
# no second lookup, and the country that picks the Ctp protocol is already
# known.

SUGGEST_LIMIT = 5


def _photon_label(props: dict) -> str:
    """Build the line a human reads in the picker."""
    street = " ".join(str(p) for p in (props.get("housenumber"), props.get("street")) if p)
    head = street or props.get("name") or ""
    tail = [
        props.get("city") or props.get("district") or props.get("county"),
        props.get("state"),
        props.get("postcode"),
        props.get("country"),
    ]
    parts = [head, *[str(t) for t in tail if t]]
    # Photon repeats the city as the name for city-level hits.
    seen: list[str] = []
    for part in parts:
        if part and (not seen or part != seen[-1]):
            seen.append(part)
    return ", ".join(seen)


def _photon_feature_to_location(feature: dict) -> Location | None:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    label = _photon_label(props)
    if not label:
        return None
    if props.get("housenumber"):
        confidence = "exact"
    elif props.get("street"):
        confidence = "interpolated"
    else:
        confidence = "approximate"
    return Location(
        lat=float(coords[1]),
        lon=float(coords[0]),
        display_name=label,
        source="photon",
        confidence=confidence,
        country_code=_norm_cc(props.get("countrycode")),
        url=build_url(PHOTON_URL, {"q": label}),
    )


@lru_cache(maxsize=256)
def _suggest_cached(query: str, limit: int) -> tuple[Location, ...]:
    url = build_url(PHOTON_URL, {"q": query, "limit": limit * 3})
    try:
        data = get_json(url)
    except HttpError as exc:
        raise GeocodingError(str(exc)) from exc

    out: list[Location] = []
    seen: set[str] = set()
    for feature in data.get("features") or []:
        location = _photon_feature_to_location(feature)
        if location is None:
            continue
        # Photon returns the same address more than once when several OSM
        # objects sit on it - a shop and the building it is in, say. The user
        # should not be asked to choose between two identical lines.
        key = location.display_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(location)
        if len(out) >= limit:
            break
    return tuple(out)


def suggest(query: str, limit: int = SUGGEST_LIMIT) -> list[Location]:
    """Candidate addresses for a partial query, best first.

    Returns [] for a query too short to be meaningful rather than sending it -
    two characters match half the planet and waste a request on a free service.
    Raises GeocodingError only if Photon could not be reached.
    """
    query = (query or "").strip()
    if len(query) < 4:
        return []
    return list(_suggest_cached(query, limit))


# --- Individual geocoders -------------------------------------------------


def geocode_census(address: str) -> Location | None:
    """US only. A plain JSON GET - geopy does not ship a Census geocoder."""
    url = build_url(
        CENSUS_URL,
        {"address": address, "benchmark": "2020", "format": "json"},
    )
    try:
        data = get_json(url)
    except HttpError as exc:
        # Not the same thing as "no such address", and a clinic behind a
        # firewall needs to be told which one it is hitting.
        raise GeocodingError(str(exc)) from exc
    matches = (data.get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    top = matches[0]
    coords = top.get("coordinates") or {}
    lat, lon = coords.get("y"), coords.get("x")
    if lat is None or lon is None:
        return None
    return Location(
        lat=float(lat),
        lon=float(lon),
        display_name=top.get("matchedAddress") or address,
        source="census",
        confidence="exact",
        country_code="US",  # US-only by construction
        url=url,
    )


def geocode_nominatim(address: str) -> Location | None:
    """Worldwide, via geopy."""
    try:
        hit = _rate_limited("nominatim")(address)
    except GeocodingError:
        raise
    except Exception as exc:
        raise GeocodingError(_transport_reason(exc)) from exc
    if hit is None:
        return None
    raw = getattr(hit, "raw", {}) or {}
    parts = raw.get("address") or {}
    cc = _norm_cc(parts.get("country_code"))
    # Key off the house number, as the Photon branch does. Nominatim's
    # `addresstype` is unreliable for this: a rooftop match on Rua Augusta 100
    # comes back as addresstype "place", which would read as approximate and
    # warn the user about a match that is in fact exact.
    if parts.get("house_number"):
        confidence = "exact"
    elif parts.get("road"):
        confidence = "interpolated"
    else:
        confidence = "approximate"
    return Location(
        lat=float(hit.latitude),
        lon=float(hit.longitude),
        display_name=str(hit.address),
        source="nominatim",
        confidence=confidence,
        country_code=cc,
        url="https://nominatim.openstreetmap.org/search?format=json&q="
        + address.replace(" ", "+"),
    )


def geocode_photon(address: str) -> Location | None:
    """Worldwide, via geopy. Returns structured fields including countrycode."""
    try:
        hit = _rate_limited("photon")(address)
    except GeocodingError:
        raise
    except Exception as exc:
        raise GeocodingError(_transport_reason(exc)) from exc
    if hit is None:
        return None
    props = (getattr(hit, "raw", {}) or {}).get("properties") or {}
    cc = _norm_cc(props.get("countrycode"))
    confidence = "exact" if props.get("housenumber") else "approximate"
    return Location(
        lat=float(hit.latitude),
        lon=float(hit.longitude),
        display_name=str(hit.address),
        source="photon",
        confidence=confidence,
        country_code=cc,
        url="https://photon.komoot.io/api/?q=" + address.replace(" ", "+"),
    )


_GEOCODERS = {
    "census": geocode_census,
    "nominatim": geocode_nominatim,
    "photon": geocode_photon,
}


# --- The chain ------------------------------------------------------------


def geocode(
    address: str,
    chain: tuple[str, ...] = GEOCODER_CHAIN,
) -> tuple[Location, list[str]]:
    """First geocoder in the chain that returns a hit, wins.

    Returns (location, notes) where notes records what was tried and skipped,
    for the calculation trace. Raises GeocodingError only if every provider
    fails or returns nothing.
    """
    address = (address or "").strip()
    if not address:
        raise GeocodingError("Please enter an address.")

    notes: list[str] = []
    no_match: list[str] = []
    unavailable: list[str] = []
    for name in chain:
        func = _GEOCODERS.get(name)
        if func is None:
            continue
        try:
            hit = func(address)
        except GeocodingError as exc:
            unavailable.append(f"{name} ({exc})")
            notes.append(f"{name} unavailable - {exc}")
            continue
        if hit is not None:
            return hit, notes
        no_match.append(name)
        notes.append(f"{name} returned no match - fell through")

    # A firewall and a typo are different problems, and the advice differs.
    if unavailable and not no_match:
        raise GeocodingError(
            "No geocoder could be reached: " + "; ".join(dict.fromkeys(unavailable))
        )
    message = f"Could not find that address. No match from: {', '.join(no_match)}."
    if unavailable:
        message += " Also could not reach: " + "; ".join(dict.fromkeys(unavailable)) + "."
    raise GeocodingError(
        message + " Check the spelling, or add the city, state/country and postal code."
    )
