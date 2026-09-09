"""The geocoder chain. No network: each provider is replaced by a stub."""

import pytest

from barome import geocode as geo
from barome.errors import GeocodingError
from barome.models import Location


def _hit(source, cc):
    return Location(
        lat=40.307,
        lon=-75.148,
        display_name=f"resolved by {source}",
        source=source,
        confidence="exact",
        country_code=cc,
    )


@pytest.fixture
def stub_chain(monkeypatch):
    def install(**funcs):
        monkeypatch.setattr(geo, "_GEOCODERS", dict(funcs))

    return install


def test_first_hit_wins(stub_chain):
    stub_chain(
        census=lambda a: _hit("census", "US"),
        nominatim=lambda a: pytest.fail("should not be reached"),
        photon=lambda a: pytest.fail("should not be reached"),
    )
    location, notes = geo.geocode("123 Main St")
    assert location.source == "census"
    assert notes == []


def test_falls_through_to_the_next_geocoder_and_records_why(stub_chain):
    stub_chain(
        census=lambda a: None,
        nominatim=lambda a: _hit("nominatim", "us"),
        photon=lambda a: pytest.fail("should not be reached"),
    )
    location, notes = geo.geocode("Rua Augusta 100, Lisboa")
    assert location.source == "nominatim"
    assert any("census" in n for n in notes)


def test_an_unreachable_geocoder_is_not_reported_as_a_typo(stub_chain):
    """A firewall and a misspelling are different problems, and the advice
    differs. Conflating them sends a clinic hunting for a typo that is not
    there."""

    def unreachable(_):
        raise GeocodingError("TLS certificate rejected")

    stub_chain(census=unreachable, nominatim=unreachable, photon=unreachable)
    with pytest.raises(GeocodingError) as caught:
        geo.geocode("Rua Augusta 100, Lisboa")
    assert "No geocoder could be reached" in str(caught.value)
    assert "spelling" not in str(caught.value)


def test_a_mix_of_no_match_and_unreachable_reports_both(stub_chain):
    def unreachable(_):
        raise GeocodingError("TLS certificate rejected")

    stub_chain(census=lambda a: None, nominatim=unreachable, photon=unreachable)
    with pytest.raises(GeocodingError) as caught:
        geo.geocode("Rua Augusta 100, Lisboa")
    message = str(caught.value)
    assert "No match from: census" in message
    assert "could not reach" in message
    assert "spelling" in message


def test_census_transport_failure_is_not_a_no_match(monkeypatch):
    from barome.net import HttpError

    def boom(url, **kw):
        raise HttpError("Could not reach census: timed out")

    monkeypatch.setattr(geo, "get_json", boom)
    with pytest.raises(GeocodingError):
        geo.geocode_census("1600 Pennsylvania Ave NW")


def test_a_geocoder_that_raises_does_not_kill_the_chain(stub_chain):
    def boom(_):
        raise GeocodingError("geopy is not installed")

    stub_chain(census=lambda a: None, nominatim=boom, photon=lambda a: _hit("photon", "PT"))
    location, notes = geo.geocode("Rua Augusta 100, Lisboa")
    assert location.source == "photon"
    assert any("unavailable" in n for n in notes)


def test_every_geocoder_failing_raises_with_advice(stub_chain):
    stub_chain(census=lambda a: None, nominatim=lambda a: None, photon=lambda a: None)
    with pytest.raises(GeocodingError, match="Check the spelling"):
        geo.geocode("asdfghjkl")


def test_an_empty_address_is_refused_before_any_request(stub_chain):
    stub_chain(census=lambda a: pytest.fail("should not be reached"))
    with pytest.raises(GeocodingError):
        geo.geocode("   ")


# --- Country code normalisation ------------------------------------------


def test_country_codes_are_normalised_to_uppercase():
    """Nominatim returns 'us', Photon returns 'US'. This is the seam where
    that difference has to disappear."""
    assert geo._norm_cc("us") == "US"
    assert geo._norm_cc("US") == "US"
    assert geo._norm_cc(" pt ") == "PT"
    assert geo._norm_cc("") is None
    assert geo._norm_cc(None) is None


def test_census_parses_a_match(monkeypatch):
    payload = {
        "result": {
            "addressMatches": [
                {
                    "matchedAddress": "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
                    "coordinates": {"x": -77.0366, "y": 38.8976},
                }
            ]
        }
    }
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: payload)
    location = geo.geocode_census("1600 Pennsylvania Ave NW, Washington, DC 20500")
    assert location.lat == pytest.approx(38.8976)
    assert location.lon == pytest.approx(-77.0366)
    assert location.country_code == "US"  # US-only by construction
    assert location.source == "census"


def test_census_returns_none_when_there_is_no_match(monkeypatch):
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: {"result": {"addressMatches": []}})
    assert geo.geocode_census("nowhere at all") is None


# --- Nominatim result parsing --------------------------------------------


class _FakeHit:
    def __init__(self, raw, address="somewhere"):
        self.raw = raw
        self.address = address
        self.latitude = 38.7101
        self.longitude = -9.1374


def _nominatim(monkeypatch, raw):
    monkeypatch.setattr(geo, "_rate_limited", lambda name: lambda addr, **kw: _FakeHit(raw))


def test_a_rooftop_match_is_not_flagged_as_approximate(monkeypatch):
    """Nominatim returns addresstype 'place' for a house-number hit on Rua
    Augusta 100. Keying off addresstype would warn the user about a match that
    is in fact exact."""
    _nominatim(
        monkeypatch,
        {
            "addresstype": "place",
            "type": "house",
            "address": {"house_number": "100", "road": "Rua Augusta", "country_code": "pt"},
        },
    )
    location = geo.geocode_nominatim("Rua Augusta 100, Lisboa")
    assert location.confidence == "exact"
    assert location.country_code == "PT"


def test_a_street_without_a_number_is_interpolated(monkeypatch):
    _nominatim(
        monkeypatch,
        {"address": {"road": "Rua Augusta", "country_code": "pt"}},
    )
    assert geo.geocode_nominatim("Rua Augusta, Lisboa").confidence == "interpolated"


def test_a_town_level_hit_is_approximate(monkeypatch):
    _nominatim(monkeypatch, {"address": {"city": "Lisboa", "country_code": "pt"}})
    assert geo.geocode_nominatim("Lisboa").confidence == "approximate"


# --- Suggestions (the address picker) ------------------------------------


def _feature(lon, lat, **props):
    return {"geometry": {"coordinates": [lon, lat]}, "properties": props}


PHOTON_SUGGESTIONS = {
    "features": [
        _feature(
            -77.0366, 38.8976,
            housenumber="1600", street="Pennsylvania Avenue Northwest",
            city="Washington", state="DC", postcode="20500",
            country="United States", countrycode="US", osm_key="office",
        ),
        # Photon returns the same address more than once when several OSM
        # objects sit on it - a shop and the building it is in, say.
        _feature(
            -77.0366, 38.8976,
            housenumber="1600", street="Pennsylvania Avenue Northwest",
            city="Washington", state="DC", postcode="20500",
            country="United States", countrycode="US", osm_key="shop",
        ),
        _feature(
            -75.1658, 39.9598,
            street="Carlton Street", city="Philadelphia", state="Pennsylvania",
            postcode="19103", country="United States", countrycode="US",
        ),
        _feature(
            -9.1374, 38.7101,
            name="Lisboa", city="Lisboa", country="Portugal", countrycode="pt",
        ),
    ]
}


@pytest.fixture(autouse=True)
def _clear_suggest_cache():
    geo._suggest_cached.cache_clear()
    yield
    geo._suggest_cached.cache_clear()


def test_suggestions_are_deduplicated(monkeypatch):
    """The user should not be asked to choose between two identical lines."""
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: PHOTON_SUGGESTIONS)
    results = geo.suggest("1600 Pennsy")
    labels = [r.display_name for r in results]
    assert len(labels) == len(set(labels))
    assert len(results) == 3


def test_a_suggestion_arrives_fully_resolved(monkeypatch):
    """Photon returns coordinates and country with the candidate, so
    confirming one costs no second lookup."""
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: PHOTON_SUGGESTIONS)
    top = geo.suggest("1600 Pennsy")[0]
    assert top.lat == pytest.approx(38.8976)
    assert top.lon == pytest.approx(-77.0366)
    assert top.country_code == "US"
    assert top.source == "photon"


def test_suggestion_labels_read_as_an_address(monkeypatch):
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: PHOTON_SUGGESTIONS)
    labels = [r.display_name for r in geo.suggest("1600 Pennsy")]
    assert labels[0] == (
        "1600 Pennsylvania Avenue Northwest, Washington, DC, 20500, United States"
    )
    # A city-level hit must not repeat itself as "Lisboa, Lisboa, Portugal".
    assert labels[2] == "Lisboa, Portugal"


def test_suggestion_confidence_tracks_how_specific_the_hit_is(monkeypatch):
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: PHOTON_SUGGESTIONS)
    results = geo.suggest("1600 Pennsy")
    assert results[0].confidence == "exact"  # has a house number
    assert results[1].confidence == "interpolated"  # street only
    assert results[2].confidence == "approximate"  # city only


def test_a_country_code_from_a_suggestion_is_normalised(monkeypatch):
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: PHOTON_SUGGESTIONS)
    assert geo.suggest("1600 Pennsy")[2].country_code == "PT"  # photon sent "pt"


@pytest.mark.parametrize("query", ["", "  ", "ab", "abc"])
def test_a_query_too_short_to_mean_anything_is_not_sent(monkeypatch, query):
    """Two characters match half the planet and waste a request on a service
    that costs nothing and asks for fair use."""
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: pytest.fail("should not be called"))
    assert geo.suggest(query) == []


def test_an_unreachable_suggestion_service_raises_rather_than_looking_empty(monkeypatch):
    """Empty means 'no such address'. A network failure must not masquerade
    as that."""
    from barome.net import HttpError

    def boom(url, **kw):
        raise HttpError("Could not reach photon")

    monkeypatch.setattr(geo, "get_json", boom)
    with pytest.raises(GeocodingError):
        geo.suggest("1600 Pennsy")


def test_a_feature_with_no_coordinates_is_skipped(monkeypatch):
    payload = {"features": [{"properties": {"name": "Nowhere"}}, *PHOTON_SUGGESTIONS["features"]]}
    monkeypatch.setattr(geo, "get_json", lambda url, **kw: payload)
    assert all(r.lat is not None for r in geo.suggest("1600 Pennsy"))
