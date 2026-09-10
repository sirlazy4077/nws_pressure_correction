"""Configuration: keys, defaults, timeouts, thresholds.

Everything a deployment might want to change lives here and can be overridden
by an environment variable, so no site has to edit code.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import ContactRequiredError

VERSION = "0.1.0"

# --- Weather Underground -------------------------------------------------
#
# WU's API is not publicly available: the free PWS tier requires contributing a
# personal weather station. The key below is the one Weather Underground's own
# website embeds in its JavaScript, i.e. this is the same request a browser
# makes when you visit wunderground.com. It works today and carries no uptime
# guarantee, which is precisely why the keyless fallbacks below ship with it
# rather than after it (plan.md 3.1).
PUBLIC_WU_API_KEY = "e1f10a1e78da46f5b10a1e78da96f525"


def wu_api_key() -> str:
    """The WU key, overridable with WU_API_KEY without a code change."""
    return os.environ.get("WU_API_KEY", "").strip() or PUBLIC_WU_API_KEY


# --- HTTP ----------------------------------------------------------------

HTTP_TIMEOUT_S = float(os.environ.get("BAROME_HTTP_TIMEOUT", "12"))

# USGS EPQS is reliably correct and reliably slow - 16 s round trips are normal.
# It gets its own budget so it is not dropped for being sluggish, which would
# quietly cost the 1 m US resolution that put it first in the chain.
USGS_TIMEOUT_S = float(os.environ.get("BAROME_USGS_TIMEOUT", "25"))

# Nominatim's usage policy requires a genuine identifying User-Agent, and it
# has to identify whoever is actually running the code - so there is no
# default. A local run (CLI or a script) must supply one; the web app supplies
# its operator's. Read at request time, not import time, so `import barome`
# never fails and a script can call set_contact() after importing.
CONTACT_ENV = "BAROME_CONTACT"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_contact_override: str | None = None


def _validated(value: str, where: str) -> str:
    value = value.strip()
    if not _EMAIL.fullmatch(value):
        raise ContactRequiredError(
            f"{value!r} (from {where}) is not an email address. The geocoding "
            "services need a real contact address they can reach you at."
        )
    return value


def set_contact(email: str) -> None:
    """Set the contact email for this process. Beats BAROME_CONTACT."""
    global _contact_override
    _contact_override = _validated(email, "set_contact()")


def contact_email() -> str:
    """The contact sent with every request, or ContactRequiredError."""
    if _contact_override:
        return _contact_override
    raw = os.environ.get(CONTACT_ENV, "").strip()
    if raw:
        return _validated(raw, CONTACT_ENV)
    raise ContactRequiredError(
        "A contact email is required. Nominatim's usage policy requires every "
        "request to identify who is making it, so barome sends your address in "
        f"the User-Agent. Set the {CONTACT_ENV} environment variable, pass "
        "--contact on the command line, or call barome.set_contact() in a script."
    )


def user_agent() -> str:
    return f"barome/{VERSION} ({contact_email()})"

# --- Chains --------------------------------------------------------------

GEOCODER_CHAIN: tuple[str, ...] = ("census", "nominatim", "photon")
ELEVATION_CHAIN: tuple[str, ...] = ("usgs", "openmeteo", "opentopodata")
PROVIDER_CHAIN: tuple[str, ...] = ("wunderground", "openmeteo", "nws")

# --- Ctp protocol --------------------------------------------------------

# A site may pin its house standard here; this suppresses the country-based
# auto-selection and says so in the display, so nobody wonders why the toggle
# "isn't working" (plan.md 5.4).
CTP_PROTOCOL_ENV = "BAROME_CTP_PROTOCOL"


def pinned_ctp_protocol() -> str | None:
    return os.environ.get(CTP_PROTOCOL_ENV, "").strip() or None


# --- Thresholds that raise user-visible warnings -------------------------

STALE_OBSERVATION_MINUTES = 120.0
DISTANT_STATION_MI = 10.0
# Above this relative gap, panel 3 asks "did you mean hPa?" rather than
# reporting a 300% discrepancy (plan.md 5.7).
UNIT_MISMATCH_FRACTION = 0.10

# How many nearby stations to walk before giving up on a provider.
MAX_STATIONS_TO_TRY = 5

# Elevation lookups are cached: a clinic re-checks the same address all day and
# the ground does not move. Observations get a short TTL because they do change.
OBSERVATION_TTL_S = 300.0

# The elevation cache also persists to disk, so a script run every hour does
# not wait on USGS every hour. On by default for local runs; the web app turns
# it off (its disk is ephemeral and shared by every session). Set to a path to
# move the file, or to 0/off to disable.
ELEVATION_CACHE_ENV = "BAROME_ELEVATION_CACHE"
_OFF = {"0", "false", "no", "off"}


def elevation_cache_path() -> Path | None:
    raw = os.environ.get(ELEVATION_CACHE_ENV, "").strip()
    if raw.lower() in _OFF:
        return None
    if raw:
        return Path(raw).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "barome" / "elevation.json"
