"""The seam, panel by panel. Every external call is stubbed."""

from datetime import UTC, datetime, timedelta

import pytest

from barome import service
from barome.errors import AllProvidersFailedError, PhysicsInputError, ProviderError
from barome.models import Location, Observation, Station
from barome.physics import CtpProtocol, Method
from barome.render import render_comparison, render_full_trace, render_steps


def _location(cc="US", source="census", confidence="exact"):
    return Location(
        lat=40.307,
        lon=-75.148,
        display_name="Doylestown, Bucks County, Pennsylvania, 18901, United States",
        source=source,
        confidence=confidence,
        country_code=cc,
        url="https://geocoding.geo.census.gov/x",
    )


def _observation(provider="wunderground", age_minutes=14.0, distance_mi=0.7):
    return Observation(
        provider=provider,
        pressure_msl_inhg=30.28,
        obs_time_utc=datetime.now(UTC) - timedelta(minutes=age_minutes),
        station=Station(
            id="KPADOYLE21",
            name="Doylestown Boro Fairgrounds",
            lat=40.31,
            lon=-75.15,
            distance_mi=distance_mi,
            elev_ft=380.0,
        ),
        quality="qcStatus 1 (passed)",
        url="https://api.weather.com/x",
        verify_url="https://www.wunderground.com/dashboard/pws/KPADOYLE21",
        note="note",
    )


class _FakeProvider:
    def __init__(self, name, observation=None, error=None):
        self.name = name
        self._observation = observation
        self._error = error
        self.calls = 0

    def fetch(self, lat, lon):
        self.calls += 1
        if self._error:
            raise ProviderError(self._error)
        return self._observation


@pytest.fixture
def wired(monkeypatch):
    """Stub the whole chain; return a knob-box the tests can adjust."""
    state = {
        "location": _location(),
        "elevation": (325.33, "usgs", "https://epqs.nationalmap.gov/x"),
        "providers": {"wunderground": _FakeProvider("wunderground", _observation())},
    }

    monkeypatch.setattr(
        service.geocode_mod, "geocode", lambda addr, chain: (state["location"], [])
    )
    monkeypatch.setattr(
        service.elevation_mod, "elevation_ft", lambda lat, lon, chain: state["elevation"]
    )

    def get_provider(name):
        provider = state["providers"].get(name)
        if provider is None:
            raise ProviderError(f"{name} not available in this test")
        return provider

    monkeypatch.setattr(service, "get_provider", get_provider)
    return state


# --- Panel 1 --------------------------------------------------------------


def test_panel_1_uses_the_address_elevation_not_the_stations(wired):
    """The bug this refactor exists for: 380 ft station vs 325 ft address is
    ~0.18% in Ctp."""
    result = service.pressure_for_address("123 Main St, Doylestown PA 18901")
    assert result.site_elev_ft == pytest.approx(325.33)
    assert result.station_elev_ft == 380.0  # carried for display only
    assert result.pressure_station_mmhg == pytest.approx(760.11, abs=0.02)


def test_panel_1_also_reports_the_legacy_value_as_a_cross_check(wired):
    result = service.pressure_for_address("123 Main St")
    assert result.pressure_station_mmhg_linear == pytest.approx(760.85, abs=0.02)
    assert result.method is Method.BAROMETRIC


def test_panel_1_holds_no_ctp_value(wired):
    """Ctp depends on a temperature supplied later and a protocol that can be
    flipped, so it must not live on this dataclass."""
    result = service.pressure_for_address("123 Main St")
    assert not hasattr(result, "ctp")
    assert result.suggested_ctp_protocol is CtpProtocol.TG_51


def test_panel_1_reports_every_unit(wired):
    result = service.pressure_for_address("123 Main St")
    assert result.pressure_station_inhg == pytest.approx(29.926, abs=0.002)
    assert result.pressure_station_hpa == pytest.approx(1013.4, abs=0.2)
    assert result.pressure_station_kpa == pytest.approx(101.34, abs=0.02)
    assert result.pressure_station_pa == pytest.approx(101340, abs=20)


def test_an_international_address_suggests_trs_398(wired):
    wired["location"] = _location(cc="pt", source="nominatim")  # lowercase, as Nominatim sends
    result = service.pressure_for_address("Rua Augusta 100, Lisboa")
    assert result.suggested_ctp_protocol is CtpProtocol.TRS_398
    assert "PT" in result.suggested_ctp_reason


# --- Provider fallback ----------------------------------------------------


def test_falls_back_when_the_primary_is_unavailable_and_never_silently(wired):
    wired["providers"] = {
        "wunderground": _FakeProvider("wunderground", error="public key rejected"),
        "openmeteo": _FakeProvider("openmeteo", _observation(provider="openmeteo")),
    }
    result = service.pressure_for_address("123 Main St")
    assert result.provider == "openmeteo"
    assert result.provider_fallback is True
    assert any("unavailable" in w for w in result.warnings)
    station_step = next(s for s in result.trace if s.stage == "station")
    assert "fallback" in station_step.provider


def test_nws_is_skipped_outside_the_us(wired):
    wired["location"] = _location(cc="PT")
    nws = _FakeProvider("nws", _observation(provider="nws"))
    wired["providers"] = {
        "wunderground": _FakeProvider("wunderground", error="down"),
        "openmeteo": _FakeProvider("openmeteo", error="down"),
        "nws": nws,
    }
    with pytest.raises(AllProvidersFailedError):
        service.pressure_for_address("Rua Augusta 100, Lisboa")
    assert nws.calls == 0


def test_every_provider_failing_says_what_was_tried(wired):
    wired["providers"] = {
        "wunderground": _FakeProvider("wunderground", error="key rejected"),
        "openmeteo": _FakeProvider("openmeteo", error="timeout"),
        "nws": _FakeProvider("nws", error="no station"),
    }
    with pytest.raises(AllProvidersFailedError, match="key rejected"):
        service.pressure_for_address("123 Main St")


# --- Warnings -------------------------------------------------------------


def test_a_stale_observation_is_flagged_on_the_step_it_belongs_to(wired):
    wired["providers"]["wunderground"] = _FakeProvider(
        "wunderground", _observation(age_minutes=200)
    )
    result = service.pressure_for_address("123 Main St")
    assert any("minutes old" in w for w in result.warnings)
    station_step = next(s for s in result.trace if s.stage == "station")
    assert any("minutes old" in w for w in station_step.warnings)


def test_a_distant_station_is_flagged(wired):
    wired["providers"]["wunderground"] = _FakeProvider(
        "wunderground", _observation(distance_mi=14.0)
    )
    result = service.pressure_for_address("123 Main St")
    assert any("14.0 miles away" in w for w in result.warnings)


def test_an_approximate_geocode_is_flagged(wired):
    wired["location"] = _location(confidence="approximate")
    result = service.pressure_for_address("Doylestown")
    assert any("only matched approximately" in w for w in result.warnings)


# --- Trace ----------------------------------------------------------------


def test_the_trace_covers_the_whole_chain_in_order(wired):
    result = service.pressure_for_address("123 Main St")
    assert [s.stage for s in result.trace] == [
        "geocode",
        "elevation",
        "station",
        "observation",
        "correction",
        "units",
    ]


def test_the_correction_step_substitutes_real_numbers(wired):
    result = service.pressure_for_address("123 Main St")
    step = next(s for s in result.trace if s.stage == "correction")
    assert "30.28" in step.expression
    assert "99.16" in step.expression  # the elevation in metres
    assert "760.11" in step.expression
    assert "legacy" in step.note


def test_the_rendered_trace_marks_the_station_elevation_unused(wired):
    result = service.pressure_for_address("123 Main St")
    text = render_steps(result.trace)
    assert "not used in the calculation" in text
    assert "not the weather station's" in text


# --- Panel 2 --------------------------------------------------------------


def test_panel_2_recomputes_without_refetching(wired):
    result = service.pressure_for_address("123 Main St")
    calls_before = wired["providers"]["wunderground"].calls
    a = service.ctp_for(result, 21.5)
    b = service.ctp_for(result, 21.5, protocol="TRS-398")
    assert wired["providers"]["wunderground"].calls == calls_before
    assert a.ctp == pytest.approx(0.9982, abs=0.0002)
    assert b.ctp == pytest.approx(1.0050, abs=0.0002)


def test_panel_2_defaults_to_the_auto_selected_protocol_and_says_so(wired):
    result = service.pressure_for_address("123 Main St")
    ctp_result = service.ctp_for(result, 21.5)
    assert ctp_result.protocol is CtpProtocol.TG_51
    assert ctp_result.protocol_source == "auto"
    assert "US" in ctp_result.protocol_reason


def test_a_manual_override_is_labelled_as_one(wired):
    result = service.pressure_for_address("123 Main St")
    ctp_result = service.ctp_for(result, 21.5, protocol="trs-398")
    assert ctp_result.protocol_source == "manual"
    assert "auto-selection was TG-51" in ctp_result.protocol_reason


def test_an_env_pin_suppresses_auto_selection_and_says_so(wired, monkeypatch):
    monkeypatch.setenv("BAROME_CTP_PROTOCOL", "TRS-398")
    result = service.pressure_for_address("123 Main St")
    ctp_result = service.ctp_for(result, 21.5)
    assert ctp_result.protocol is CtpProtocol.TRS_398
    assert ctp_result.protocol_source == "env"
    assert "suppressed" in ctp_result.protocol_reason


def test_an_explicit_choice_beats_the_env_pin(wired, monkeypatch):
    monkeypatch.setenv("BAROME_CTP_PROTOCOL", "TRS-398")
    result = service.pressure_for_address("123 Main St")
    ctp_result = service.ctp_for(result, 21.5, protocol="TG-51")
    assert ctp_result.protocol is CtpProtocol.TG_51
    assert ctp_result.protocol_source == "manual"


def test_the_unselected_protocol_is_always_shown_too(wired):
    result = service.pressure_for_address("123 Main St")
    ctp_result = service.ctp_for(result, 21.5)
    assert ctp_result.other_protocol is CtpProtocol.TRS_398
    assert ctp_result.ctp_other_protocol == pytest.approx(1.0050, abs=0.0002)
    assert ctp_result.other_delta_pct == pytest.approx(0.6821, abs=0.01)


# --- Panel 3 --------------------------------------------------------------


@pytest.fixture
def panel2(wired):
    result = service.pressure_for_address("123 Main St")
    return result, service.ctp_for(result, 21.5)


def test_panel_3_reports_the_ctp_difference(panel2):
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, 757.0, "mmHg", 21.8)
    assert comparison.ctp_calculated == pytest.approx(0.9982, abs=0.0002)
    assert comparison.ctp_local == pytest.approx(1.0033, abs=0.0002)
    assert comparison.d_ctp == pytest.approx(0.0051, abs=0.0002)
    assert comparison.d_ctp_pct == pytest.approx(0.513, abs=0.01)


def test_panel_3_reports_no_pressure_or_temperature_difference(panel2):
    """Ctp is what propagates into a dose measurement, so Ctp is the only
    comparison. The pressure and temperature are inputs, echoed for checking."""
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, 757.0, "mmHg", 21.8)
    fields = set(vars(comparison))
    assert not {"d_pressure_mmhg", "d_pressure_pct", "d_temp_c", "d_temp_pct_kelvin"} & fields
    text = render_comparison(comparison)
    assert "difference" in text
    assert text.count("difference") == 1


def test_a_blank_temperature_inherits_rather_than_defaulting_to_zero(panel2):
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, 757.0, "mmHg", None)
    assert comparison.local_temp_inherited is True
    assert comparison.local_temp_c == pytest.approx(21.5)


@pytest.mark.parametrize(
    "value,unit",
    [(757.0, "mmHg"), (29.8031, "inHg"), (1009.25, "hPa"), (100.925, "kPa")],
)
def test_the_unit_dropdown_round_trips(panel2, value, unit):
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, value, unit, 21.8)
    assert comparison.local_pressure_mmhg == pytest.approx(757.0, abs=0.05)
    assert comparison.local_pressure_input == value
    assert comparison.local_pressure_unit == unit


def test_the_protocol_is_inherited_and_cannot_diverge(panel2):
    """Two Ctp values under different references would mix an instrument
    difference with a 0.6775% convention difference."""
    result, _ = panel2
    trs = service.ctp_for(result, 21.5, protocol="TRS-398")
    comparison = service.compare_local(trs, 757.0, "mmHg", 21.8)
    assert comparison.protocol is CtpProtocol.TRS_398
    assert "protocol" not in _signature_of(service.compare_local)


def _signature_of(func):
    import inspect

    return list(inspect.signature(func).parameters)


def test_a_unit_mixup_is_questioned_not_reported_as_a_300_percent_fault(panel2):
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, 1013.0, "mmHg", 21.8)
    assert any("Did you mean hPa?" in w for w in comparison.warnings)


def test_no_tolerance_or_pass_fail_flag_is_produced(panel2):
    """Whether a given difference is acceptable is a clinical judgement, and
    the tool does not make it."""
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, 757.0, "mmHg", 21.8)
    fields = set(vars(comparison))
    assert not {"within_tolerance", "passed", "tolerance_pct", "flag"} & fields


# --- Bug #10: division by zero, at the input boundary ---------------------


def test_zero_pressure_raises_a_readable_error(panel2):
    _, ctp_result = panel2
    with pytest.raises(PhysicsInputError, match="greater than zero"):
        service.compare_local(ctp_result, 0.0, "mmHg", 21.8)


def test_absolute_zero_temperature_raises_a_readable_error(panel2):
    _, ctp_result = panel2
    with pytest.raises(PhysicsInputError, match="absolute zero"):
        service.compare_local(ctp_result, 757.0, "mmHg", -273.2)


def test_zero_celsius_is_perfectly_fine(panel2):
    """The old code raised ZeroDivisionError at exactly 0 °C because it took a
    percentage of an interval scale. Nothing about 0 °C is special here."""
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, 757.0, "mmHg", 0.0)
    assert comparison.ctp_local > 0


def test_implausible_but_possible_readings_pass_with_a_warning(panel2):
    _, ctp_result = panel2
    comparison = service.compare_local(ctp_result, 400.0, "mmHg", -55.0)
    assert comparison.ctp_local > 0
    assert len(comparison.warnings) >= 2


# --- Whole-record export --------------------------------------------------


def test_the_export_includes_only_the_panels_that_were_filled_in(wired):
    result = service.pressure_for_address("123 Main St")
    pressure_only = render_full_trace(result)
    assert "7. Ctp" not in pressure_only
    assert "INTERCOMPARISON" not in pressure_only
    assert pressure_only.rstrip().endswith("133.322387415 Pa")  # ends at step 6

    ctp_result = service.ctp_for(result, 21.5)
    comparison = service.compare_local(ctp_result, 757.0, "mmHg", 21.8)
    everything = render_full_trace(result, ctp_result, comparison)
    assert "7. Ctp" in everything
    assert "8. INTERCOMPARISON" in everything


# --- A confirmed address skips the geocoder chain -------------------------


def test_a_confirmed_candidate_is_not_geocoded_again(wired, monkeypatch):
    """A suggestion arrives fully resolved, so confirming one must not spend a
    second lookup - nor risk the chain resolving it somewhere else."""
    monkeypatch.setattr(
        service.geocode_mod,
        "geocode",
        lambda addr, chain: pytest.fail("should not geocode a confirmed address"),
    )
    picked = _location(cc="PT", source="photon")
    result = service.pressure_for_address("Rua Augusta 100", location=picked)
    assert result.lat == picked.lat
    assert result.resolved_address == picked.display_name
    assert result.suggested_ctp_protocol is CtpProtocol.TRS_398


def test_a_confirmed_address_says_so_in_the_trace(wired):
    picked = _location(source="photon")
    result = service.pressure_for_address("123 Main St", location=picked)
    step = next(s for s in result.trace if s.stage == "geocode")
    assert "confirmed by you" in step.provider
    assert "confirmed by the user" in step.note


def test_a_confirmed_address_is_not_second_guessed(wired):
    """Warning that an address 'only matched approximately' after the user has
    read it in full and chosen it trains them to ignore the warning."""
    picked = _location(confidence="approximate", source="photon")
    result = service.pressure_for_address("Doylestown", location=picked)
    assert not any("only matched approximately" in w for w in result.warnings)

    # But an unconfirmed one still is.
    wired["location"] = _location(confidence="approximate")
    unconfirmed = service.pressure_for_address("Doylestown")
    assert any("only matched approximately" in w for w in unconfirmed.warnings)
