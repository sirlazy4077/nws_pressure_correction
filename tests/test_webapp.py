"""The three panels, driven headlessly through Streamlit's AppTest.

These exist because the panel rules are behavioural, not arithmetic: what is
shown where, what survives an address change, and what a blank field means.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from barome import service  # noqa: E402
from barome.models import Location, PressureResult, TraceStep  # noqa: E402
from barome.physics import CtpProtocol, Method  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "web" / "app.py")


def _fake_result(address: str, country="US", protocol=CtpProtocol.TG_51) -> PressureResult:
    return PressureResult(
        address_query=address,
        resolved_address=f"resolved: {address}",
        lat=40.307,
        lon=-75.148,
        country_code=country,
        geocoder="census",
        geocode_confidence="exact",
        provider="wunderground",
        provider_fallback=False,
        station_id="KPADOYLE21",
        station_name="Doylestown Boro Fairgrounds",
        station_distance_mi=0.7,
        station_elev_ft=380.0,
        obs_time_utc=datetime.now(UTC),
        obs_age_minutes=14.0,
        site_elev_ft=325.33,
        elev_source="USGS EPQS (NED, 1 m)",
        pressure_msl_inhg=30.28,
        pressure_station_mmhg=760.11,
        pressure_station_inhg=29.926,
        pressure_station_hpa=1013.40,
        pressure_station_kpa=101.340,
        pressure_station_pa=101340.0,
        pressure_station_mmhg_linear=760.85,
        method=Method.BAROMETRIC,
        suggested_ctp_protocol=protocol,
        suggested_ctp_reason=f"address resolved to {country}",
        trace=[TraceStep(stage="geocode", provider="census", output={"resolved": address})],
        source_urls={},
        warnings=[],
    )


def _candidate(label, cc="US"):
    return Location(
        lat=40.307,
        lon=-75.148,
        display_name=label,
        source="photon",
        confidence="exact",
        country_code=cc,
    )


SUGGESTIONS = [
    _candidate("123 S Main St, Doylestown, PA 18901, United States"),
    _candidate("123 N Main St, Doylestown, PA 18901, United States"),
]


@pytest.fixture
def app(monkeypatch):
    """An app whose only network calls are stubbed."""
    calls = []
    suggested = []

    def fake_lookup(address, **kwargs):
        calls.append((address, kwargs.get("location")))
        return _fake_result(address)

    def fake_suggest(query, *a, **kw):
        suggested.append(query)
        return list(SUGGESTIONS)

    monkeypatch.setattr(service, "pressure_for_address", fake_lookup)
    monkeypatch.setattr(service, "suggest_addresses", fake_suggest)
    at = AppTest.from_file(APP, default_timeout=30)
    at.calls = calls
    at.suggested = suggested
    return at


def _find(at, address):
    """Type an address and press Find, stopping at the candidate list."""
    at.run()
    at.text_input[0].set_value(address)
    at.button[0].click().run()
    return at


def _run_with_address(at, address, choice=0):
    """The whole panel-1 flow: type, find, pick a candidate, confirm."""
    _find(at, address)
    at.radio[0].set_value(choice).run()
    at.button[1].click().run()
    return at


def test_the_page_loads_and_asks_for_an_address(app):
    app.run()
    assert not app.exception
    assert any("Enter an address" in i.value for i in app.info)


def test_panel_1_shows_the_pressure_without_a_temperature(app):
    _run_with_address(app, "123 Main St")
    assert not app.exception
    assert app.metric[0].value == "760.11 mmHg"


def test_panel_1_never_mentions_a_protocol(app):
    """No reference protocol is involved in producing that number, and
    implying otherwise would be wrong."""
    _run_with_address(app, "123 Main St")
    assert app.radio.values == []  # the toggle has not appeared yet
    labels = " ".join(m.label for m in app.metric)
    assert "TG-51" not in labels and "TRS-398" not in labels


def test_panel_2_appears_only_once_a_temperature_is_entered(app):
    _run_with_address(app, "123 Main St")
    assert len(app.metric) == 1
    app.number_input[0].set_value(21.5).run()
    assert not app.exception
    assert len(app.radio) == 1  # the protocol toggle, in panel 2
    assert any("Ctp" in m.label for m in app.metric)


def test_panel_2_preselects_the_auto_protocol_and_recomputes_without_refetching(app):
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    fetches = len(app.calls)

    ctp_metric = next(m for m in app.metric if "Ctp" in m.label)
    assert "TG-51" in ctp_metric.label
    assert ctp_metric.value == "0.9982"

    app.radio[0].set_value(CtpProtocol.TRS_398).run()
    ctp_metric = next(m for m in app.metric if "Ctp" in m.label)
    assert "TRS-398" in ctp_metric.label
    assert ctp_metric.value == "1.0050"
    # No refetch: the toggle is pure arithmetic over the cached result.
    assert len(app.calls) == fetches


def test_panel_3_waits_for_panel_2(app):
    _run_with_address(app, "123 Main St")
    assert any("Enter a temperature above first" in i.value for i in app.info)


def test_panel_3_reports_the_ctp_difference_only(app):
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    app.number_input[1].set_value(757.0).run()
    assert not app.exception

    labels = [m.label for m in app.metric]
    assert "Ctp calculated" in labels
    assert "Ctp yours" in labels
    assert "Difference" in labels
    # Not a pressure difference and not a temperature difference.
    assert not any("pressure" in label.lower() for label in labels[1:])
    assert not any("temp" in label.lower() for label in labels)


def test_panel_3_inherits_a_blank_temperature_rather_than_using_zero(app):
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    app.number_input[1].set_value(757.0).run()
    assert any("inherited from the Ctp panel" in c.value for c in app.caption)


def test_panel_3_inherits_the_protocol_from_panel_2(app):
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    app.number_input[1].set_value(757.0).run()
    app.radio[0].set_value(CtpProtocol.TRS_398).run()
    assert any("Both at TRS-398" in c.value for c in app.caption)
    # And there is still exactly one protocol control on the page.
    assert len(app.radio) == 1


def test_a_unit_mixup_is_questioned(app):
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    app.number_input[1].set_value(1013.0).run()
    assert any("Did you mean hPa?" in w.value for w in app.warning)


def test_zero_pressure_shows_a_readable_error_not_a_traceback(app):
    """plan.md bug #10, at the front end: the user sees a sentence, not a
    ZeroDivisionError."""
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    app.number_input[1].set_value(0.0).run()
    assert not app.exception
    assert any("greater than zero" in e.value for e in app.error)


# --- The rule that every panel must follow when the address changes -------


def test_changing_the_address_clears_the_previous_result(app):
    """No panel may display a number belonging to a previous address."""
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    assert any("Ctp" in m.label for m in app.metric)

    # Type a different address without pressing Go.
    app.text_input[0].set_value("456 Other Ave").run()
    assert not app.exception
    assert app.metric.values == []  # panel 1 gone
    assert app.radio.values == []  # panel 2's protocol toggle gone
    assert any("Enter an address" in i.value for i in app.info)


def test_a_new_address_recalculates_every_panel(app):
    _run_with_address(app, "123 Main St")
    app.number_input[0].set_value(21.5).run()
    _run_with_address(app, "456 Other Ave")
    assert not app.exception
    assert [address for address, _ in app.calls] == ["123 Main St", "456 Other Ave"]
    shown = [e.value for e in app.markdown] + [e.value for e in app.caption]
    assert any("456 Other Ave" in text for text in shown)
    assert not any("123 Main St" in text for text in shown)


# --- The address picker ---------------------------------------------------


def test_find_offers_candidates_before_looking_anything_up(app):
    _find(app, "123 Main St")
    assert not app.exception
    assert app.suggested == ["123 Main St"]
    assert app.calls == []  # nothing looked up until a candidate is confirmed
    labels = app.radio[0].options
    assert "123 S Main St, Doylestown, PA 18901, United States" in labels


def test_the_last_option_always_escapes_the_suggestion_service(app):
    """OpenStreetMap does not know every address; in the US the Census
    geocoder often does. The picker must never be a dead end."""
    _find(app, "123 Main St")
    assert app.radio[0].options[-1] == "None of these - use exactly what I typed"


def test_confirming_a_candidate_passes_it_through_so_nothing_is_geocoded_twice(app):
    _run_with_address(app, "123 Main St", choice=1)
    address, location = app.calls[0]
    assert address == "123 Main St"
    assert location is not None
    assert location.display_name == "123 N Main St, Doylestown, PA 18901, United States"


def test_choosing_none_of_these_falls_back_to_the_full_geocoder_chain(app):
    _find(app, "123 Main St")
    app.radio[0].set_value(len(SUGGESTIONS)).run()
    app.button[1].click().run()
    assert not app.exception
    address, location = app.calls[0]
    assert location is None  # service.geocode() decides, Census first


def test_the_picker_collapses_once_an_address_is_confirmed(app):
    _run_with_address(app, "123 Main St")
    assert app.radio.values == []
    assert app.metric[0].value == "760.11 mmHg"


def test_changing_the_address_clears_the_candidate_list_too(app):
    """A candidate list belonging to a different query is exactly as wrong as
    a result belonging to a different address."""
    _find(app, "123 Main St")
    assert len(app.radio) == 1
    app.text_input[0].set_value("456 Other Ave").run()
    assert app.radio.values == []
    assert any("press **Find address**" in i.value for i in app.info)


def test_no_suggestions_still_allows_a_direct_lookup(app, monkeypatch):
    monkeypatch.setattr(service, "suggest_addresses", lambda q, *a, **kw: [])
    _find(app, "Somewhere OSM has never heard of")
    assert any("No suggestions matched" in w.value for w in app.warning)
    app.button[1].click().run()
    assert not app.exception
    assert app.calls[0][1] is None


def test_an_unreachable_suggestion_service_is_reported_not_swallowed(app, monkeypatch):
    from barome.errors import GeocodingError

    def boom(query, *a, **kw):
        raise GeocodingError("Could not reach photon")

    monkeypatch.setattr(service, "suggest_addresses", boom)
    _find(app, "123 Main St")
    assert any("Could not reach photon" in e.value for e in app.error)
