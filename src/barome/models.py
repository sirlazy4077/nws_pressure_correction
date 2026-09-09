"""Frozen dataclasses passed between the layers.

These are the vocabulary of the package: the service returns them, both front
ends render them, and the tests assert on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .physics import CtpProtocol, Method


@dataclass(frozen=True)
class TraceStep:
    """One stage of the calculation, recorded as it ran.

    Each stage appends its own step, so the trace cannot drift out of sync with
    the calculation that produced it.
    """

    stage: str  # "geocode" | "elevation" | "station" | "observation"
    #                          | "correction" | "units" | "ctp" | "intercomparison"
    provider: str  # which service actually answered
    inputs: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    expression: str | None = None  # the formula with real numbers substituted in
    url: str | None = None  # the exact request, so the user can click it
    note: str | None = None  # e.g. "census returned no match - fell through"
    # Warnings live on the step they belong to, not in a footer: a station 14
    # miles away is flagged where the user is already looking.
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    display_name: str  # echoed back so the user can confirm the match
    source: str  # "census" | "nominatim" | "photon"
    confidence: str  # "exact" | "interpolated" | "approximate"
    country_code: str | None = None  # normalised uppercase; drives auto_protocol
    url: str | None = None


@dataclass(frozen=True)
class Station:
    """A weather station. Open-Meteo has none - it is a model grid - so the
    provider layer is allowed to return None rather than invent one."""

    id: str | None
    name: str | None
    lat: float | None
    lon: float | None
    distance_mi: float | None
    elev_ft: float | None  # displayed for comparison, NEVER used in the correction


@dataclass(frozen=True)
class Observation:
    """What every provider returns: a sea-level pressure plus its provenance.

    The elevation correction is deliberately not a provider's job - it happens
    once, in physics.py, against the user's own elevation. That keeps the trace
    identical in shape no matter which source answered.
    """

    provider: str  # "wunderground" | "openmeteo" | "nws"
    pressure_msl_inhg: float
    obs_time_utc: datetime
    station: Station
    quality: str | None = None  # provider's own QC flag, verbatim
    url: str | None = None  # the API request that produced this
    verify_url: str | None = None  # a human-readable page, where one exists
    note: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PressureResult:
    """Panel 1: the pressure at this address.

    Deliberately holds no Ctp value and only a *suggested* protocol. Ctp
    depends on a temperature the user supplies afterwards and on a protocol
    they can flip at any time, so both live in the Ctp panel. That is what lets
    panel 1 stand alone and lets the panel-2 toggle recompute from cached
    values instead of re-running the whole chain.
    """

    # what the user typed, and what we decided it meant
    address_query: str
    resolved_address: str
    lat: float
    lon: float
    country_code: str | None
    geocoder: str
    geocode_confidence: str
    # where the pressure came from - always shown, never hidden
    provider: str
    provider_fallback: bool
    station_id: str | None
    station_name: str | None
    station_distance_mi: float | None
    station_elev_ft: float | None  # displayed, but NOT used in the correction
    obs_time_utc: datetime
    obs_age_minutes: float
    # the site's own elevation, and where that number came from
    site_elev_ft: float
    elev_source: str
    # the numbers
    pressure_msl_inhg: float
    pressure_station_mmhg: float
    pressure_station_inhg: float
    pressure_station_hpa: float
    pressure_station_kpa: float
    pressure_station_pa: float
    pressure_station_mmhg_linear: float  # legacy cross-check
    method: Method
    # Ctp protocol: suggested here, applied in the Ctp panel
    suggested_ctp_protocol: CtpProtocol
    suggested_ctp_reason: str
    # provenance and honesty
    trace: list[TraceStep] = field(default_factory=list)
    source_urls: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CtpResult:
    """Panel 2. Recomputed locally from a cached PressureResult - no refetch."""

    ctp: float
    temperature_c: float
    pressure_mmhg: float
    protocol: CtpProtocol
    protocol_source: str  # "auto" | "manual" | "env"
    protocol_reason: str
    ctp_other_protocol: float  # the unselected protocol's value, always shown
    other_protocol: CtpProtocol
    other_delta_pct: float
    trace: list[TraceStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IntercomparisonResult:
    """Panel 3. Reports one thing: the difference between two Ctp values."""

    # what the user measured - echoed for verification, not compared
    local_pressure_mmhg: float
    local_pressure_input: float  # as typed, before unit conversion
    local_pressure_unit: str  # "mmHg" | "inHg" | "hPa" | "kPa"
    local_temp_c: float
    local_temp_inherited: bool  # True if panel 2's temperature was reused
    # the comparison
    ctp_calculated: float
    ctp_local: float
    d_ctp: float
    d_ctp_pct: float
    protocol: CtpProtocol  # inherited from panel 2, never chosen here
    trace: list[TraceStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
