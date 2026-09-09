"""The seam. One contract, called by both front ends.

Nothing here prompts and nothing here prints. That is the single change that
made a web app possible: the old code's `pressure()` prompted, scraped,
computed, printed and looped in one body, so no view could call any of it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import elevation as elevation_mod
from . import geocode as geocode_mod
from .config import (
    DISTANT_STATION_MI,
    ELEVATION_CHAIN,
    GEOCODER_CHAIN,
    PROVIDER_CHAIN,
    STALE_OBSERVATION_MINUTES,
    UNIT_MISMATCH_FRACTION,
    pinned_ctp_protocol,
)
from .errors import AllProvidersFailedError, ProviderError
from .models import (
    CtpResult,
    IntercomparisonResult,
    Observation,
    PressureResult,
    TraceStep,
)
from .physics import (
    CELSIUS_TO_KELVIN,
    MMHG_PER_INHG,
    REFERENCE_PRESSURE_MMHG,
    REFERENCE_TEMP_C,
    CtpProtocol,
    Method,
    auto_protocol,
    barometric_factor,
    convert_pressure_units,
    ctp,
    ctp_difference,
    msl_to_station_pressure,
    other_protocol,
    parse_protocol,
    plausibility_warnings,
    to_mmhg,
    validate_inputs,
)
from .providers import get_provider
from .providers import label as provider_label

DEFAULT_PROVIDER = "wunderground"


# --- Provider chain -------------------------------------------------------


def _provider_order(preferred: str, country_code: str | None) -> list[str]:
    """Preferred first, then the rest of the chain. NWS is skipped outside the
    US rather than allowed to fail slowly."""
    order = [preferred] + [p for p in PROVIDER_CHAIN if p != preferred]
    if country_code and country_code.upper() != "US":
        order = [p for p in order if p != "nws"]
    return order


def _fetch_with_fallback(
    lat: float,
    lon: float,
    preferred: str,
    country_code: str | None,
) -> tuple[Observation, bool, list[str]]:
    """Returns (observation, was_fallback, notes).

    Falling back is never silent: it raises a warning on the result and is
    written into the trace, so a user always knows which source produced their
    number and that the preferred one was unavailable.
    """
    notes: list[str] = []
    problems: list[str] = []
    order = _provider_order(preferred, country_code)
    for index, name in enumerate(order):
        try:
            observation = get_provider(name).fetch(lat, lon)
        except (ProviderError, ValueError) as exc:
            problems.append(f"{provider_label(name)}: {exc}")
            notes.append(f"{provider_label(name)} unavailable - {exc}")
            continue
        return observation, index > 0, notes
    raise AllProvidersFailedError(
        "No pressure source could be reached. " + " | ".join(problems)
    )


# --- Panel 1 --------------------------------------------------------------


def pressure_for_address(
    address: str,
    *,
    provider: str = DEFAULT_PROVIDER,
    method: Method = Method.BAROMETRIC,
    geocoder_chain: tuple[str, ...] = GEOCODER_CHAIN,
    elevation_chain: tuple[str, ...] = ELEVATION_CHAIN,
) -> PressureResult:
    """The user types one thing. This resolves everything else."""
    trace: list[TraceStep] = []
    warnings: list[str] = []
    urls: dict[str, str] = {}

    # 1. ADDRESS ----------------------------------------------------------
    location, geo_notes = geocode_mod.geocode(address, geocoder_chain)
    urls["geocode"] = location.url or ""
    geo_warnings: list[str] = []
    if location.confidence == "approximate":
        geo_warnings.append(
            f"The address only matched approximately, to '{location.display_name}'. "
            "Check that this is the right place before using the result."
        )
    warnings.extend(geo_warnings)
    trace.append(
        TraceStep(
            stage="geocode",
            provider=location.source,
            inputs={"address": address},
            output={
                "resolved": location.display_name,
                "lat": round(location.lat, 5),
                "lon": round(location.lon, 5),
                "country": location.country_code,
                "confidence": location.confidence,
            },
            url=location.url,
            note="; ".join(geo_notes) or None,
            warnings=tuple(geo_warnings),
        )
    )

    # 2. ELEVATION - at the address, not the station ----------------------
    elev_ft, elev_key, elev_url = elevation_mod.elevation_ft(
        location.lat, location.lon, elevation_chain
    )
    urls["elevation"] = elev_url
    trace.append(
        TraceStep(
            stage="elevation",
            provider=elevation_mod.source_label(elev_key),
            inputs={"lat": round(location.lat, 5), "lon": round(location.lon, 5)},
            output={"elevation_ft": round(elev_ft, 2), "elevation_m": round(elev_ft * 0.3048, 2)},
            url=elev_url,
            note="This is the elevation at your address, not the weather station's.",
        )
    )

    # 3-4. PRESSURE SOURCE -------------------------------------------------
    observation, was_fallback, provider_notes = _fetch_with_fallback(
        location.lat, location.lon, provider, location.country_code
    )
    station = observation.station
    urls["observation"] = observation.verify_url or observation.url or ""

    age_min = (
        datetime.now(UTC) - observation.obs_time_utc.astimezone(UTC)
    ).total_seconds() / 60.0

    station_warnings: list[str] = list(observation.warnings)
    if was_fallback:
        station_warnings.append(
            f"{provider_label(provider)} was unavailable; this reading came from "
            f"{provider_label(observation.provider)} instead."
        )
    if age_min > STALE_OBSERVATION_MINUTES:
        station_warnings.append(
            f"This observation is {age_min:.0f} minutes old. Consider re-checking, "
            "or read your own barometer."
        )
    if station.distance_mi is not None and station.distance_mi > DISTANT_STATION_MI:
        station_warnings.append(
            f"The nearest reporting station is {station.distance_mi:.1f} miles away. "
            "Local weather may differ."
        )
    warnings.extend(station_warnings)

    trace.append(
        TraceStep(
            stage="station",
            provider=provider_label(observation.provider)
            + (" (fallback)" if was_fallback else " (primary)"),
            inputs={"lat": round(location.lat, 5), "lon": round(location.lon, 5)},
            output={
                "station_id": station.id,
                "station_name": station.name,
                "distance_mi": round(station.distance_mi, 2) if station.distance_mi else None,
                "station_elev_ft": station.elev_ft,
                "observed_utc": observation.obs_time_utc.isoformat(timespec="seconds"),
                "age_minutes": round(age_min, 1),
                "quality": observation.quality,
            },
            url=observation.verify_url or observation.url,
            note="; ".join([n for n in [observation.note, *provider_notes] if n]) or None,
            warnings=tuple(station_warnings),
        )
    )
    trace.append(
        TraceStep(
            stage="observation",
            provider=provider_label(observation.provider),
            inputs={},
            output={"pressure_msl_inhg": round(observation.pressure_msl_inhg, 4)},
            url=observation.url,
        )
    )

    # 5. ELEVATION CORRECTION ---------------------------------------------
    p_station_inhg = msl_to_station_pressure(observation.pressure_msl_inhg, elev_ft, method)
    p_linear_inhg = msl_to_station_pressure(
        observation.pressure_msl_inhg, elev_ft, Method.LINEAR
    )
    factor = barometric_factor(elev_ft)
    h_m = elev_ft * 0.3048

    if method is Method.BAROMETRIC:
        expression = (
            "P_station = P_msl x (1 - 0.0065 x h / 288.15) ^ 5.25588\n"
            f"          = {observation.pressure_msl_inhg:.2f} x "
            f"(1 - 0.0065 x {h_m:.2f} / 288.15) ^ 5.25588\n"
            f"          = {observation.pressure_msl_inhg:.2f} x {factor:.5f}\n"
            f"          = {p_station_inhg:.4f} inHg\n"
            f"          = {p_station_inhg * MMHG_PER_INHG:.2f} mmHg"
        )
    else:
        expression = (
            "P_station = P_msl - elevation_ft / 1000    [legacy rule of thumb]\n"
            f"          = {observation.pressure_msl_inhg:.2f} - {elev_ft:.2f} / 1000\n"
            f"          = {p_station_inhg:.4f} inHg\n"
            f"          = {p_station_inhg * MMHG_PER_INHG:.2f} mmHg"
        )

    linear_mmhg = p_linear_inhg * MMHG_PER_INHG
    station_mmhg = p_station_inhg * MMHG_PER_INHG
    trace.append(
        TraceStep(
            stage="correction",
            provider="standard atmosphere" if method is Method.BAROMETRIC else "legacy linear",
            inputs={
                "P_msl_inHg": round(observation.pressure_msl_inhg, 4),
                "elevation_ft": round(elev_ft, 2),
                "elevation_m": round(h_m, 2),
            },
            output={
                "P_station_inHg": round(p_station_inhg, 4),
                "P_station_mmHg": round(station_mmhg, 2),
            },
            expression=expression,
            note=(
                f"Cross-check: legacy 1 inHg/1000 ft rule gives {linear_mmhg:.2f} mmHg "
                f"({linear_mmhg - station_mmhg:+.2f} mmHg)."
                if method is Method.BAROMETRIC
                else None
            ),
        )
    )

    # 6. UNITS -------------------------------------------------------------
    units = convert_pressure_units(p_station_inhg)
    trace.append(
        TraceStep(
            stage="units",
            provider="exact conversion factors",
            inputs={"P_station_inHg": round(p_station_inhg, 4)},
            output={k: round(v, 3) for k, v in units.items()},
            expression="1 inHg = 25.4 mmHg exactly; 1 mmHg = 133.322387415 Pa",
        )
    )

    suggested, reason = auto_protocol(location.country_code)

    return PressureResult(
        address_query=address,
        resolved_address=location.display_name,
        lat=location.lat,
        lon=location.lon,
        country_code=location.country_code,
        geocoder=location.source,
        geocode_confidence=location.confidence,
        provider=observation.provider,
        provider_fallback=was_fallback,
        station_id=station.id,
        station_name=station.name,
        station_distance_mi=station.distance_mi,
        station_elev_ft=station.elev_ft,
        obs_time_utc=observation.obs_time_utc,
        obs_age_minutes=age_min,
        site_elev_ft=elev_ft,
        elev_source=elevation_mod.source_label(elev_key),
        pressure_msl_inhg=observation.pressure_msl_inhg,
        pressure_station_mmhg=units["mmHg"],
        pressure_station_inhg=units["inHg"],
        pressure_station_hpa=units["hPa"],
        pressure_station_kpa=units["kPa"],
        pressure_station_pa=units["Pa"],
        pressure_station_mmhg_linear=linear_mmhg,
        method=method,
        suggested_ctp_protocol=suggested,
        suggested_ctp_reason=reason,
        trace=trace,
        source_urls=urls,
        warnings=warnings,
    )


# --- Panel 2 --------------------------------------------------------------


def resolve_protocol(
    result: PressureResult,
    override: str | CtpProtocol | None = None,
) -> tuple[CtpProtocol, str, str]:
    """Precedence: explicit override > BAROME_CTP_PROTOCOL > country.

    Returns (protocol, source, reason). An env-var pin suppresses the
    auto-selection and says so, so a physicist never wonders why the toggle
    "isn't working".
    """
    chosen = parse_protocol(override)
    if chosen is not None:
        auto = result.suggested_ctp_protocol
        if chosen is auto:
            return chosen, "manual", f"selected by hand (matches the auto-selection: {auto})"
        return chosen, "manual", f"manually overridden (auto-selection was {auto})"

    pinned = parse_protocol(pinned_ctp_protocol())
    if pinned is not None:
        return (
            pinned,
            "env",
            f"pinned by BAROME_CTP_PROTOCOL - auto-selection ({result.suggested_ctp_protocol}) "
            "is suppressed",
        )

    return result.suggested_ctp_protocol, "auto", f"auto-selected: {result.suggested_ctp_reason}"


def ctp_for(
    result: PressureResult,
    temperature_c: float,
    *,
    protocol: str | CtpProtocol | None = None,
) -> CtpResult:
    """Panel 2. Pure arithmetic over a cached PressureResult - no refetch, so
    flipping the protocol recomputes instantly and locally."""
    pressure_mmhg = result.pressure_station_mmhg
    validate_inputs(temperature_c, pressure_mmhg)

    chosen, source, reason = resolve_protocol(result, protocol)
    value = ctp(temperature_c, pressure_mmhg, chosen)
    alt = other_protocol(chosen)
    alt_value = ctp(temperature_c, pressure_mmhg, alt)

    t_ref = REFERENCE_TEMP_C[chosen]
    expression = (
        "Ctp = (273.2 + T) / (273.2 + T_ref) x (760.0 / P)\n"
        f"    = (273.2 + {temperature_c:g}) / (273.2 + {t_ref:g}) x (760.0 / {pressure_mmhg:.2f})\n"
        f"    = {(CELSIUS_TO_KELVIN + temperature_c) / (CELSIUS_TO_KELVIN + t_ref):.5f} x "
        f"{REFERENCE_PRESSURE_MMHG / pressure_mmhg:.5f}\n"
        f"    = {value:.4f}"
    )

    ctp_warnings = plausibility_warnings(temperature_c, pressure_mmhg)
    step = TraceStep(
        stage="ctp",
        provider=f"{chosen} ({t_ref:g} °C reference)",
        inputs={
            "temperature_C": temperature_c,
            "pressure_mmHg": round(pressure_mmhg, 2),
            "protocol": str(chosen),
            "protocol_source": source,
        },
        output={"ctp": round(value, 4)},
        expression=expression,
        note=(
            f"{reason}. If {alt} ({REFERENCE_TEMP_C[alt]:g} °C) were selected instead: "
            f"{alt_value:.4f} ({(alt_value / value - 1) * 100:+.2f}%)."
        ),
        warnings=tuple(ctp_warnings),
    )

    return CtpResult(
        ctp=value,
        temperature_c=temperature_c,
        pressure_mmhg=pressure_mmhg,
        protocol=chosen,
        protocol_source=source,
        protocol_reason=reason,
        ctp_other_protocol=alt_value,
        other_protocol=alt,
        other_delta_pct=(alt_value / value - 1) * 100.0,
        trace=[step],
        warnings=ctp_warnings,
    )


# --- Panel 3 --------------------------------------------------------------


def compare_local(
    ctp_result: CtpResult,
    local_pressure: float,
    local_pressure_unit: str = "mmHg",
    local_temp_c: float | None = None,
) -> IntercomparisonResult:
    """Panel 3: how far is the clinic's own Ctp from the derived one?

    Reports the Ctp difference and nothing else. Pressure and temperature are
    inputs to the second Ctp; they are echoed back so the user can confirm what
    was entered, but they are not reported as differences. Ctp is what
    propagates into a dose measurement, so Ctp is what the comparison is about.
    """
    local_mmhg = to_mmhg(local_pressure, local_pressure_unit)
    inherited = local_temp_c is None
    temp_c = ctp_result.temperature_c if inherited else float(local_temp_c)

    # The input boundary: refuse the physically impossible with a readable
    # message rather than letting a ZeroDivisionError escape (bug #10).
    validate_inputs(temp_c, local_mmhg)

    # The protocol is inherited from panel 2 and is not selectable here. Two
    # Ctp values under different references would mix an instrument difference
    # with a 0.6775% convention difference, and the result would be
    # uninterpretable.
    protocol = ctp_result.protocol
    local_ctp = ctp(temp_c, local_mmhg, protocol)
    d_ctp, d_pct = ctp_difference(ctp_result.ctp, local_ctp)

    warnings = plausibility_warnings(temp_c, local_mmhg)
    gap = abs(local_mmhg - ctp_result.pressure_mmhg) / ctp_result.pressure_mmhg
    if gap > UNIT_MISMATCH_FRACTION:
        warnings.append(
            f"Your pressure ({local_mmhg:.2f} mmHg) differs from the calculated one "
            f"({ctp_result.pressure_mmhg:.2f} mmHg) by {gap * 100:.0f}%. "
            "Did you mean hPa? Check the unit before trusting this comparison."
        )

    t_ref = REFERENCE_TEMP_C[protocol]
    expression = (
        f"Ctp (calculated) = (273.2 + {ctp_result.temperature_c:g}) / (273.2 + {t_ref:g}) "
        f"x (760.0 / {ctp_result.pressure_mmhg:.2f}) = {ctp_result.ctp:.4f}\n"
        f"Ctp (yours)      = (273.2 + {temp_c:g}) / (273.2 + {t_ref:g}) "
        f"x (760.0 / {local_mmhg:.2f}) = {local_ctp:.4f}\n"
        f"difference       = {local_ctp:.4f} - {ctp_result.ctp:.4f} = {d_ctp:+.4f} "
        f"({d_pct:+.3f}%)"
    )

    step = TraceStep(
        stage="intercomparison",
        provider=f"{protocol} ({t_ref:g} °C reference, inherited from the Ctp panel)",
        inputs={
            "entered_pressure": f"{local_pressure:g} {local_pressure_unit}",
            "converted_pressure_mmHg": round(local_mmhg, 2),
            "temperature_C": temp_c,
            "temperature_source": "inherited from the Ctp panel" if inherited else "entered here",
        },
        output={
            "ctp_calculated": round(ctp_result.ctp, 4),
            "ctp_yours": round(local_ctp, 4),
            "difference": round(d_ctp, 4),
            "difference_pct": round(d_pct, 3),
        },
        expression=expression,
        note="Both Ctp values use the same reference protocol, so this is an "
        "instrument difference only.",
        warnings=tuple(warnings),
    )

    return IntercomparisonResult(
        local_pressure_mmhg=local_mmhg,
        local_pressure_input=float(local_pressure),
        local_pressure_unit=local_pressure_unit,
        local_temp_c=temp_c,
        local_temp_inherited=inherited,
        ctp_calculated=ctp_result.ctp,
        ctp_local=local_ctp,
        d_ctp=d_ctp,
        d_ctp_pct=d_pct,
        protocol=protocol,
        trace=[step],
        warnings=warnings,
    )
