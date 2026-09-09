"""Pure physics. No network, no I/O, no printing.

Everything here is a function of its arguments, which is what makes it testable
and what lets both front ends recompute a Ctp instantly from cached values
instead of re-running the whole lookup chain.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import PhysicsInputError

# --- Unit constants ------------------------------------------------------
#
# Named, not inlined. The old code carried 0.03937 as a magic number; that is
# a rounded 1/25.4 and it is replaced here by the exact value.

M_PER_FT = 0.3048
FT_PER_M = 1.0 / M_PER_FT

MMHG_PER_INHG = 25.4
PA_PER_MMHG = 133.322387415  # conventional millimetre of mercury (= 1 torr)
PA_PER_INHG = PA_PER_MMHG * MMHG_PER_INHG  # 3386.388640341
PA_PER_HPA = 100.0
PA_PER_KPA = 1000.0

# --- Standard atmosphere (plan.md 2.4c, "the table method") --------------
#
#   P_station = P_msl * (1 - L*h / T0) ** (g*M / (R*L))
#             = P_msl * (1 - 0.0065*h / 288.15) ** 5.25588
#
# with h in metres. The exponent follows from standard gravity, the molar mass
# of dry air and the universal gas constant.

LAPSE_RATE_K_PER_M = 0.0065  # tropospheric lapse rate L
SEA_LEVEL_TEMP_K = 288.15  # ISA sea-level temperature T0
BAROMETRIC_EXPONENT = 5.25588  # g*M / (R*L)

# --- Ctp -----------------------------------------------------------------

REFERENCE_PRESSURE_MMHG = 760.0
# The dosimetry convention is 273.2, not 273.15. Kept as the protocols write it.
CELSIUS_TO_KELVIN = 273.2
# The physical bound, which is what validation is actually about.
ABSOLUTE_ZERO_C = -273.15

# Outside these, a reading is unusual but not impossible: warn, never refuse.
PLAUSIBLE_PRESSURE_MMHG = (225.0, 825.0)  # ~9000 m up to a record sea-level high
PLAUSIBLE_TEMP_C = (-50.0, 60.0)


class Method(StrEnum):
    """How sea-level pressure is corrected to the site's own elevation."""

    BAROMETRIC = "barometric"  # DEFAULT - standard atmosphere
    LINEAR = "linear"  # legacy 1 inHg/1000 ft, cross-check only


class CtpProtocol(StrEnum):
    TG_51 = "TG-51"  # 22.0 C reference  <- DEFAULT (AAPM, US standard)
    TRS_398 = "TRS-398"  # 20.0 C reference     (IAEA, international)


REFERENCE_TEMP_C: dict[CtpProtocol, float] = {
    CtpProtocol.TG_51: 22.0,
    CtpProtocol.TRS_398: 20.0,
}

DEFAULT_CTP_PROTOCOL = CtpProtocol.TG_51

PROTOCOL_LABEL: dict[CtpProtocol, str] = {
    CtpProtocol.TG_51: "AAPM TG-51",
    CtpProtocol.TRS_398: "IAEA TRS-398",
}

# Territories included defensively. Every one of these actually reports "US"
# from the geocoders in the chain, but a geocoder that behaves differently is
# the difference between a clinic in San Juan getting TG-51 and getting a
# silently wrong protocol (plan.md 5.4).
US_CODES = frozenset({"US", "PR", "GU", "VI", "AS", "MP"})


def parse_protocol(value: str | CtpProtocol | None) -> CtpProtocol | None:
    """Accept 'TG-51', 'tg51', 'trs-398', 'trs398'... case and hyphen agnostic."""
    if value is None:
        return None
    if isinstance(value, CtpProtocol):
        return value
    key = value.strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    if key in {"TG51", "AAPMTG51", "22", "22C"}:
        return CtpProtocol.TG_51
    if key in {"TRS398", "IAEATRS398", "20", "20C"}:
        return CtpProtocol.TRS_398
    return None


# --- Elevation correction ------------------------------------------------


def msl_to_station_pressure(
    p_msl_inhg: float,
    elev_ft: float,
    method: Method = Method.BAROMETRIC,
) -> float:
    """Correct a sea-level-adjusted pressure to the pressure at `elev_ft`.

    Every provider in this package normalises to MSL, so this is the single
    correction path regardless of which one answered.
    """
    if method is Method.BAROMETRIC:
        h_m = elev_ft * M_PER_FT
        return p_msl_inhg * (1.0 - LAPSE_RATE_K_PER_M * h_m / SEA_LEVEL_TEMP_K) ** BAROMETRIC_EXPONENT
    # Legacy "1 inHg per 1000 ft" rule of thumb, retained only as a labelled
    # cross-check so numbers in existing records stay reproducible.
    return p_msl_inhg - elev_ft / 1000.0


def barometric_factor(elev_ft: float) -> float:
    """The multiplier alone, so the trace can show it on its own line."""
    h_m = elev_ft * M_PER_FT
    return (1.0 - LAPSE_RATE_K_PER_M * h_m / SEA_LEVEL_TEMP_K) ** BAROMETRIC_EXPONENT


# --- Unit conversion -----------------------------------------------------


def convert_pressure_units(p_inhg: float) -> dict[str, float]:
    """One pressure, every unit a physicist might want it in."""
    mmhg = p_inhg * MMHG_PER_INHG
    pa = p_inhg * PA_PER_INHG
    return {
        "inHg": p_inhg,
        "mmHg": mmhg,
        "hPa": pa / PA_PER_HPA,
        "kPa": pa / PA_PER_KPA,
        "Pa": pa,
    }


PRESSURE_UNITS = ("mmHg", "inHg", "hPa", "kPa")


def to_mmhg(value: float, unit: str) -> float:
    """Convert a user-entered pressure to mmHg.

    The unit is explicit and required. A clinic barometer reading 1013 hPa
    typed into a field expecting mmHg is a silent 33% error that produces a
    plausible-looking number.
    """
    key = unit.strip().lower()
    if key == "mmhg" or key == "torr":
        return float(value)
    if key == "inhg":
        return float(value) * MMHG_PER_INHG
    if key in {"hpa", "mbar", "millibar"}:
        return float(value) * PA_PER_HPA / PA_PER_MMHG
    if key == "kpa":
        return float(value) * PA_PER_KPA / PA_PER_MMHG
    if key == "pa":
        return float(value) / PA_PER_MMHG
    raise PhysicsInputError(f"Unknown pressure unit: {unit!r}. Use one of {', '.join(PRESSURE_UNITS)}.")


# --- Validation ----------------------------------------------------------
#
# plan.md bug #10. Two division-by-zero paths are reachable from user input:
#   P = 0            -> 760.0 / P
#   T = -273.2 C     -> (273.2 + T) = 0, so Ctp = 0, so any percent
#                       difference against it divides by zero
# The fix belongs at the input boundary, not at each division, so the user gets
# a readable domain error instead of an arithmetic exception from three frames
# down.


def validate_inputs(temp_c: float, pressure_mmhg: float) -> None:
    """Refuse the physically impossible. Raises PhysicsInputError."""
    if pressure_mmhg <= 0:
        raise PhysicsInputError(
            f"Pressure must be greater than zero (got {pressure_mmhg:g} mmHg)."
        )
    if temp_c <= ABSOLUTE_ZERO_C:
        raise PhysicsInputError(
            f"Temperature must be above absolute zero ({ABSOLUTE_ZERO_C} °C); got {temp_c:g} °C."
        )


def plausibility_warnings(temp_c: float, pressure_mmhg: float) -> list[str]:
    """Flag the merely unusual. Never rejects: the tool should still work
    somewhere unusual."""
    out: list[str] = []
    lo, hi = PLAUSIBLE_PRESSURE_MMHG
    if not (lo <= pressure_mmhg <= hi):
        out.append(
            f"Pressure {pressure_mmhg:.2f} mmHg is outside the usual range "
            f"{lo:g}-{hi:g} mmHg. Calculated anyway - check the value and its units."
        )
    lo, hi = PLAUSIBLE_TEMP_C
    if not (lo <= temp_c <= hi):
        out.append(
            f"Temperature {temp_c:.2f} °C is outside the usual range {lo:g}-{hi:g} °C. "
            "Calculated anyway - check the value."
        )
    return out


# --- Ctp -----------------------------------------------------------------


def ctp(
    temp_c: float,
    pressure_mmhg: float,
    protocol: CtpProtocol = DEFAULT_CTP_PROTOCOL,
) -> float:
    """Temperature-pressure correction factor.

        Ctp = (273.2 + T) / (273.2 + T_ref) * (760.0 / P)
    """
    validate_inputs(temp_c, pressure_mmhg)
    t_ref = REFERENCE_TEMP_C[protocol]
    return ((CELSIUS_TO_KELVIN + temp_c) / (CELSIUS_TO_KELVIN + t_ref)) * (
        REFERENCE_PRESSURE_MMHG / pressure_mmhg
    )


def protocol_ratio(frm: CtpProtocol, to: CtpProtocol) -> float:
    """Ctp(to) / Ctp(frm) - a pure constant, independent of T and P.

    TG-51 -> TRS-398 is +0.6775% on every result, which is why the protocol is
    restated on every rendering rather than assumed.
    """
    return (CELSIUS_TO_KELVIN + REFERENCE_TEMP_C[frm]) / (
        CELSIUS_TO_KELVIN + REFERENCE_TEMP_C[to]
    )


def other_protocol(protocol: CtpProtocol) -> CtpProtocol:
    return CtpProtocol.TRS_398 if protocol is CtpProtocol.TG_51 else CtpProtocol.TG_51


def auto_protocol(country_code: str | None) -> tuple[CtpProtocol, str]:
    """Pick the reference protocol from the resolved address's country.

    Returns (protocol, human-readable reason). The reason is displayed, always:
    the auto-selection is a starting point, never a silent decision.
    """
    if not country_code:
        return (
            CtpProtocol.TG_51,
            "country could not be resolved - defaulted to the US standard",
        )
    # Nominatim returns a lowercase country_code, Photon an uppercase one.
    # Without this normalisation every Nominatim-resolved US address silently
    # gets TRS-398.
    cc = country_code.strip().upper()
    if cc in US_CODES:
        return CtpProtocol.TG_51, f"address resolved to {cc} → AAPM TG-51 (US standard)"
    return (
        CtpProtocol.TRS_398,
        f"address resolved to {cc} → IAEA TRS-398 (international standard)",
    )


# --- Intercomparison -----------------------------------------------------


def ctp_difference(ctp_calculated: float, ctp_local: float) -> tuple[float, float]:
    """(absolute, percent) difference between two Ctp values.

    Ctp is what propagates into a dose measurement, so Ctp is what panel 3
    compares - not pressure, not temperature.
    """
    if ctp_calculated == 0:
        raise PhysicsInputError(
            "The calculated Ctp is zero, so a percent difference is undefined. "
            "Check the temperature and pressure inputs."
        )
    d = ctp_local - ctp_calculated
    return d, (d / ctp_calculated) * 100.0


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles. Used for station distance when a
    provider does not report one."""
    from math import asin, cos, radians, sin, sqrt

    r_mi = 3958.7613
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r_mi * asin(sqrt(a))
