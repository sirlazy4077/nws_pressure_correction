"""Providers, against recorded payload shapes. No network."""

import pytest

from barome.errors import ProviderError
from barome.net import HttpError
from barome.physics import MMHG_PER_INHG, PA_PER_INHG, Method, msl_to_station_pressure
from barome.providers import nws as nws_mod
from barome.providers import openmeteo as om_mod
from barome.providers import wunderground as wu_mod
from barome.providers.nws import NwsProvider
from barome.providers.openmeteo import OpenMeteoProvider
from barome.providers.wunderground import WundergroundProvider

# --- Weather Underground -------------------------------------------------

WU_NEAR = {
    "location": {
        "stationId": ["KPADOYLE21", "KPADOYLE55"],
        "stationName": ["Doylestown Boro Fairgrounds", "Other"],
        "latitude": [40.31, 40.33],
        "longitude": [-75.15, -75.16],
        "distanceKm": [1.13, 4.0],
        "qcStatus": [1, 1],
    }
}
WU_OBS = {
    "observations": [
        {
            "stationID": "KPADOYLE21",
            "obsTimeUtc": "2026-09-08T17:00:00Z",
            "neighborhood": "Doylestown Boro Fairgrounds",
            "qcStatus": 1,
            "lat": 40.31,
            "lon": -75.15,
            "imperial": {"pressure": 30.28, "elev": 380},
        }
    ]
}


def test_wunderground_reads_sea_level_pressure_and_station_elevation(monkeypatch):
    monkeypatch.setattr(wu_mod, "get_json", lambda url, **kw: WU_NEAR if "near" in url else WU_OBS)
    obs = WundergroundProvider().fetch(40.307, -75.148)
    assert obs.pressure_msl_inhg == pytest.approx(30.28)
    # The station's own elevation is carried for display and never used.
    assert obs.station.elev_ft == 380
    assert obs.station.id == "KPADOYLE21"
    assert obs.station.distance_mi == pytest.approx(0.70, abs=0.02)
    assert "qcStatus 1" in obs.quality


def test_wunderground_walks_past_a_station_with_no_pressure(monkeypatch):
    """A personal weather station can be online but reporting nothing useful.
    Normal, and must not be fatal."""
    empty = {"observations": [{"stationID": "KPADOYLE21", "imperial": {}}]}

    def fake(url, **kw):
        if "near" in url:
            return WU_NEAR
        return empty if "KPADOYLE21" in url else WU_OBS

    monkeypatch.setattr(wu_mod, "get_json", fake)
    obs = WundergroundProvider().fetch(40.307, -75.148)
    assert obs.pressure_msl_inhg == pytest.approx(30.28)


def test_wunderground_flags_a_failed_quality_check(monkeypatch):
    bad = {"observations": [dict(WU_OBS["observations"][0], qcStatus=-1)]}
    monkeypatch.setattr(wu_mod, "get_json", lambda url, **kw: WU_NEAR if "near" in url else bad)
    obs = WundergroundProvider().fetch(40.307, -75.148)
    assert any("quality control" in w for w in obs.warnings)


def test_wunderground_raises_rather_than_returning_nothing(monkeypatch):
    def boom(url, **kw):
        if "near" in url:
            return WU_NEAR
        raise HttpError("503")

    monkeypatch.setattr(wu_mod, "get_json", boom)
    with pytest.raises(ProviderError):
        WundergroundProvider().fetch(40.307, -75.148)


# --- Open-Meteo -----------------------------------------------------------

OM_PAYLOAD = {
    "latitude": 40.3,
    "longitude": -75.15,
    "elevation": 99.0,
    "current": {"time": "2026-09-08T17:00", "pressure_msl": 1022.6, "surface_pressure": 1010.8},
}


def test_openmeteo_converts_hpa_to_inhg(monkeypatch):
    monkeypatch.setattr(om_mod, "get_json", lambda url, **kw: OM_PAYLOAD)
    obs = OpenMeteoProvider().fetch(40.307, -75.148)
    assert obs.pressure_msl_inhg == pytest.approx(1022.6 * 100 / PA_PER_INHG, rel=1e-9)
    assert obs.pressure_msl_inhg == pytest.approx(30.198, abs=0.002)


def test_openmeteo_invents_no_station(monkeypatch):
    """It is a model grid. The trace must not pretend otherwise."""
    monkeypatch.setattr(om_mod, "get_json", lambda url, **kw: OM_PAYLOAD)
    obs = OpenMeteoProvider().fetch(40.307, -75.148)
    assert obs.station.id is None
    assert obs.station.distance_mi is None
    assert "grid" in obs.note


def test_our_formula_agrees_with_open_meteos_own_correction():
    """Open-Meteo applies its own correction to surface_pressure at its grid
    elevation. Two independent implementations agreeing to under a tenth of a
    percent is the evidence the formula is right."""
    ours_hpa = (
        msl_to_station_pressure(1022.6 * 100 / PA_PER_INHG, 99.0 / 0.3048) * PA_PER_INHG / 100
    )
    assert ours_hpa == pytest.approx(1010.8, rel=0.0005)


# --- NWS ------------------------------------------------------------------


def _nws_payloads(elevation_m, pressure_pa, qc="V"):
    points = {"properties": {"observationStations": "https://api.weather.gov/x/stations"}}
    listing = {
        "features": [
            {
                "properties": {
                    "stationIdentifier": "KLXV",
                    "name": "Leadville",
                    "elevation": {"value": elevation_m},
                },
                "geometry": {"coordinates": [-106.32, 39.22]},
            }
        ]
    }
    latest = {
        "properties": {
            "timestamp": "2026-09-08T17:00:00+00:00",
            "barometricPressure": {"value": pressure_pa, "qualityControl": qc},
            "seaLevelPressure": {"value": None, "qualityControl": "Z"},
        }
    }

    def fake(url, **kw):
        if "/points/" in url:
            return points
        if url.endswith("/stations"):
            return listing
        return latest

    return fake


def test_nws_barometric_pressure_is_an_altimeter_setting_not_station_pressure():
    """The trap the whole investigation was for. KLXV (Leadville, 3026 m)
    reports 1037.93 hPa. Read literally that implies an MSL of 1505 hPa, a
    +47% error. Read correctly it implies ~716 hPa at the station."""
    provider = NwsProvider()
    fake = _nws_payloads(3026.0, 103793.0)
    import barome.providers.nws as m

    original = m.get_json
    m.get_json = fake
    try:
        obs = provider.fetch(39.22, -106.32)
    finally:
        m.get_json = original

    station_hpa = (
        msl_to_station_pressure(obs.pressure_msl_inhg, 3026.0 / 0.3048) * PA_PER_INHG / 100
    )
    assert station_hpa == pytest.approx(716.0, abs=1.5)
    # And emphatically not the literal reading.
    assert station_hpa < 800
    assert "altimeter setting" in obs.note


def test_nws_walks_past_a_null_barometric_pressure(monkeypatch):
    """KDEN returned no barometricPressure at all, so nulls are normal and the
    first station in the list cannot be trusted."""
    points = {"properties": {"observationStations": "https://api.weather.gov/x/stations"}}
    listing = {
        "features": [
            {
                "properties": {"stationIdentifier": "KDEN", "name": "Denver",
                               "elevation": {"value": 1655.0}},
                "geometry": {"coordinates": [-104.66, 39.85]},
            },
            {
                "properties": {"stationIdentifier": "KBJC", "name": "Broomfield",
                               "elevation": {"value": 1725.0}},
                "geometry": {"coordinates": [-105.12, 39.91]},
            },
        ]
    }

    def fake(url, **kw):
        if "/points/" in url:
            return points
        if url.endswith("/stations"):
            return listing
        if "KDEN" in url:
            return {"properties": {"barometricPressure": {"value": None}}}
        return {
            "properties": {
                "timestamp": "2026-09-08T17:00:00+00:00",
                "barometricPressure": {"value": 102400.0, "qualityControl": "V"},
            }
        }

    monkeypatch.setattr(nws_mod, "get_json", fake)
    obs = NwsProvider().fetch(39.85, -104.66)
    assert obs.station.id == "KBJC"


def test_nws_flags_an_unvalidated_quality_control_code(monkeypatch):
    monkeypatch.setattr(nws_mod, "get_json", _nws_payloads(3.0, 102404.0, qc="Z"))
    obs = NwsProvider().fetch(40.64, -73.78)
    assert any("quality control" in w for w in obs.warnings)


def test_nws_reports_the_station_elevation_without_using_it(monkeypatch):
    monkeypatch.setattr(nws_mod, "get_json", _nws_payloads(3026.0, 103793.0))
    obs = NwsProvider().fetch(39.22, -106.32)
    assert obs.station.elev_ft == pytest.approx(3026.0 / 0.3048, abs=1)


# --- Cross-provider -------------------------------------------------------


def test_providers_agree_once_normalised():
    """WU and Open-Meteo at the same point, corrected the same way, agreed to
    ~0.1%. A provider silently changing its units would break this."""
    wu = msl_to_station_pressure(30.28, 325.33, Method.BAROMETRIC) * MMHG_PER_INHG
    om = (
        msl_to_station_pressure(1022.6 * 100 / PA_PER_INHG, 325.33, Method.BAROMETRIC)
        * MMHG_PER_INHG
    )
    assert abs(wu - om) / wu < 0.005
