"""The pure core. No network, so these run anywhere, fast."""

import math

import pytest

from barome.errors import PhysicsInputError
from barome.physics import (
    MMHG_PER_INHG,
    CtpProtocol,
    Method,
    auto_protocol,
    convert_pressure_units,
    ctp,
    ctp_difference,
    msl_to_station_pressure,
    parse_protocol,
    plausibility_warnings,
    protocol_ratio,
    to_mmhg,
    validate_inputs,
)

# plan.md 2.4(c). This table is the fixture: it is the evidence the linear rule
# of thumb was dropped for, so it is what pins the replacement.
#   elevation_ft, linear_mmHg, barometric_mmHg
TABLE = [
    (0, 759.97, 759.97),
    (500, 747.27, 746.34),
    (1000, 734.57, 732.90),
    (2000, 709.17, 706.63),
    (3000, 683.77, 681.11),
    (5000, 632.97, 632.33),
    (7000, 582.17, 586.41),
]
P_MSL = 29.92


@pytest.mark.parametrize("elev_ft,linear,barometric", TABLE)
def test_correction_table(elev_ft, linear, barometric):
    got_b = msl_to_station_pressure(P_MSL, elev_ft, Method.BAROMETRIC) * MMHG_PER_INHG
    got_l = msl_to_station_pressure(P_MSL, elev_ft, Method.LINEAR) * MMHG_PER_INHG
    assert got_b == pytest.approx(barometric, abs=0.05)
    assert got_l == pytest.approx(linear, abs=0.05)


def test_barometric_is_the_default():
    assert msl_to_station_pressure(P_MSL, 3000) == msl_to_station_pressure(
        P_MSL, 3000, Method.BAROMETRIC
    )


def test_linear_and_barometric_diverge_where_it_matters():
    """The reason for the change: ~0.4% through the elevations most of the US
    lives at, and a sign reversal above ~6000 ft."""
    at_3000 = msl_to_station_pressure(P_MSL, 3000, Method.LINEAR) - msl_to_station_pressure(
        P_MSL, 3000, Method.BAROMETRIC
    )
    at_7000 = msl_to_station_pressure(P_MSL, 7000, Method.LINEAR) - msl_to_station_pressure(
        P_MSL, 7000, Method.BAROMETRIC
    )
    assert at_3000 > 0
    assert at_7000 < 0


def test_worked_example_from_the_plan():
    """P_msl 30.28 inHg at 325.33 ft -> 29.9257 inHg = 760.11 mmHg."""
    inhg = msl_to_station_pressure(30.28, 325.33)
    assert inhg == pytest.approx(29.9257, abs=0.0005)
    assert inhg * MMHG_PER_INHG == pytest.approx(760.11, abs=0.02)


def test_unit_conversions_are_exact_not_rounded():
    """The old code carried 0.03937 as a magic number; 1/25.4 is exact."""
    units = convert_pressure_units(1.0)
    assert units["mmHg"] == 25.4
    assert units["Pa"] == pytest.approx(3386.388640341, abs=1e-6)
    assert units["hPa"] == pytest.approx(33.86388640341, abs=1e-8)
    assert units["kPa"] == pytest.approx(3.386388640341, abs=1e-9)


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        (760.0, "mmHg", 760.0),
        (29.92, "inHg", 759.968),
        (1013.25, "hPa", 759.999),
        (101.325, "kPa", 759.999),
    ],
)
def test_to_mmhg(value, unit, expected):
    assert to_mmhg(value, unit) == pytest.approx(expected, abs=0.01)


def test_to_mmhg_round_trips_through_every_unit():
    for unit in ("mmHg", "inHg", "hPa", "kPa"):
        units = convert_pressure_units(29.9257)
        assert to_mmhg(units[unit], unit) == pytest.approx(units["mmHg"], abs=1e-9)


def test_to_mmhg_rejects_an_unknown_unit():
    with pytest.raises(PhysicsInputError):
        to_mmhg(760.0, "furlongs")


# --- Ctp -----------------------------------------------------------------


def test_ctp_worked_example_both_protocols():
    assert ctp(21.5, 760.11, CtpProtocol.TG_51) == pytest.approx(0.9982, abs=0.0001)
    assert ctp(21.5, 760.11, CtpProtocol.TRS_398) == pytest.approx(1.0050, abs=0.0001)


def test_protocol_shift_is_a_uniform_constant():
    """The whole reason the protocol is restated on every rendering: switching
    it moves every Ctp by exactly -0.6775%, whatever T and P are."""
    expected = 293.2 / 295.2
    for temp in (-10.0, 0.0, 20.0, 21.5, 37.0):
        for pressure in (500.0, 760.0, 800.0):
            got = ctp(temp, pressure, CtpProtocol.TG_51) / ctp(
                temp, pressure, CtpProtocol.TRS_398
            )
            assert got == pytest.approx(expected, rel=1e-12)
    assert (expected - 1) * 100 == pytest.approx(-0.6775, abs=0.0001)
    assert protocol_ratio(CtpProtocol.TRS_398, CtpProtocol.TG_51) == pytest.approx(expected)


def test_old_behaviour_was_trs_398():
    """The old code hard-coded 20.0 C. Pinning it here makes the default change
    a reviewed artefact rather than a surprise."""
    old = ((273.2 + 21.5) / (273.2 + 20.0)) * (760.0 / 760.11)
    assert ctp(21.5, 760.11, CtpProtocol.TRS_398) == pytest.approx(old, rel=1e-12)


# --- Protocol auto-selection ---------------------------------------------


def test_nominatim_lowercase_country_code_still_gets_tg51():
    """Nominatim returns 'us', Photon returns 'US'. Without normalisation every
    Nominatim-resolved US address silently gets TRS-398."""
    protocol, reason = auto_protocol("us")
    assert protocol is CtpProtocol.TG_51
    assert "US" in reason


@pytest.mark.parametrize("code", ["US", "us", "PR", "GU", "VI", "AS", "MP"])
def test_us_and_its_territories_get_tg51(code):
    assert auto_protocol(code)[0] is CtpProtocol.TG_51


@pytest.mark.parametrize("code", ["PT", "JP", "gb", "DE"])
def test_everywhere_else_gets_trs398(code):
    assert auto_protocol(code)[0] is CtpProtocol.TRS_398


def test_unresolved_country_falls_back_to_the_us_standard_and_says_so():
    protocol, reason = auto_protocol(None)
    assert protocol is CtpProtocol.TG_51
    assert "could not be resolved" in reason


@pytest.mark.parametrize(
    "text,expected",
    [
        ("TG-51", CtpProtocol.TG_51),
        ("tg51", CtpProtocol.TG_51),
        ("TRS-398", CtpProtocol.TRS_398),
        ("trs398", CtpProtocol.TRS_398),
        ("nonsense", None),
        (None, None),
    ],
)
def test_parse_protocol(text, expected):
    assert parse_protocol(text) is expected


# --- Validation: plan.md bug #10 -----------------------------------------


def test_zero_pressure_raises_a_readable_error_not_zerodivision():
    with pytest.raises(PhysicsInputError, match="greater than zero"):
        ctp(21.5, 0.0)


def test_negative_pressure_is_refused():
    with pytest.raises(PhysicsInputError):
        validate_inputs(21.5, -10.0)


def test_absolute_zero_raises_rather_than_producing_a_zero_ctp():
    """(273.2 + T) = 0 makes Ctp zero, so any percent difference against it
    divides by zero. Caught at the boundary instead."""
    with pytest.raises(PhysicsInputError, match="absolute zero"):
        ctp(-273.2, 760.0)


def test_implausible_but_possible_values_are_computed_with_a_warning():
    """The tool should not refuse to work somewhere unusual."""
    value = ctp(-60.0, 200.0)
    assert math.isfinite(value)
    warnings = plausibility_warnings(-60.0, 200.0)
    assert len(warnings) == 2
    assert any("Pressure" in w for w in warnings)
    assert any("Temperature" in w for w in warnings)


def test_ordinary_values_warn_about_nothing():
    assert plausibility_warnings(21.5, 760.1) == []


def test_ctp_difference_is_reported_as_absolute_and_percent():
    d, pct = ctp_difference(0.998162, 1.003273)
    assert d == pytest.approx(0.0051, abs=0.0001)
    assert pct == pytest.approx(0.512, abs=0.01)


def test_ctp_difference_refuses_a_zero_denominator():
    with pytest.raises(PhysicsInputError):
        ctp_difference(0.0, 1.0)
