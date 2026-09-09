"""The elevation chain, including the sentinel that makes it work abroad."""

import pytest

from barome import elevation as elev
from barome.errors import ElevationError


@pytest.fixture(autouse=True)
def _clear_cache():
    elev._cached.cache_clear()
    yield
    elev._cached.cache_clear()


def test_usgs_answers_first_when_it_can(monkeypatch):
    monkeypatch.setattr(elev, "_usgs", lambda lat, lon: (325.33, "usgs", "u"))
    monkeypatch.setattr(elev, "_openmeteo", lambda lat, lon: pytest.fail("not reached"))
    monkeypatch.setattr(
        elev, "_SOURCES", {"usgs": elev._usgs, "openmeteo": elev._openmeteo}
    )
    feet, source, _ = elev.elevation_ft(40.307, -75.148)
    assert feet == pytest.approx(325.33)
    assert source == "usgs"


def test_usgs_off_grid_sentinel_falls_through(monkeypatch):
    """USGS returns -1000000 outside its DEM. Treating that as a miss is what
    lets the chain work for non-US addresses with no country check."""
    monkeypatch.setattr(elev, "get_json", lambda url, **kw: {"value": elev.USGS_OFF_GRID})
    assert elev._usgs(38.71, -9.14) is None


def test_usgs_parses_feet_directly(monkeypatch):
    monkeypatch.setattr(elev, "get_json", lambda url, **kw: {"value": "325.33"})
    feet, key, _ = elev._usgs(40.307, -75.148)
    assert feet == pytest.approx(325.33)
    assert key == "usgs"


def test_openmeteo_metres_are_converted_to_feet(monkeypatch):
    monkeypatch.setattr(elev, "get_json", lambda url, **kw: {"elevation": [99.0]})
    feet, key, _ = elev._openmeteo(40.307, -75.148)
    assert feet == pytest.approx(324.80, abs=0.01)
    assert key == "openmeteo"


def test_opentopodata_prefers_the_finer_us_dataset(monkeypatch):
    seen = []

    def fake(url, **kw):
        seen.append(url)
        return {"results": [{"elevation": 99.2}]}

    monkeypatch.setattr(elev, "get_json", fake)
    feet, key, _ = elev._opentopodata(40.307, -75.148)
    assert "ned10m" in seen[0]
    assert key == "opentopodata-ned10m"
    assert feet == pytest.approx(325.46, abs=0.02)


def test_every_source_failing_raises(monkeypatch):
    monkeypatch.setattr(
        elev,
        "_SOURCES",
        {"usgs": lambda *a: None, "openmeteo": lambda *a: None, "opentopodata": lambda *a: None},
    )
    with pytest.raises(ElevationError):
        elev.elevation_ft(0.0, 0.0)


def test_repeat_lookups_are_cached(monkeypatch):
    calls = []

    def counting(lat, lon):
        calls.append((lat, lon))
        return (325.33, "usgs", "u")

    monkeypatch.setattr(elev, "_SOURCES", {"usgs": counting})
    elev.elevation_ft(40.30701, -75.14802, ("usgs",))
    elev.elevation_ft(40.30702, -75.14801, ("usgs",))  # same to 4 dp
    assert len(calls) == 1


def test_the_choice_of_source_barely_matters():
    """Six sources spanned 13.1 ft at the test point: 0.044% in Ctp, four times
    smaller than the station-vs-address error this fixes. Guard the claim."""
    readings = [324.80, 325.33, 325.39, 331.36, 334.65, 337.93]
    spread_inhg = (max(readings) - min(readings)) / 1000.0
    assert max(readings) - min(readings) == pytest.approx(13.13, abs=0.02)
    assert spread_inhg * 25.4 / 760.0 * 100 < 0.05  # percent in Ctp
