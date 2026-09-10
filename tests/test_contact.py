"""A local run must name a contact; the web app names its operator's."""

import io

import cli
import pytest

from barome import config, geocode, net, service
from barome.errors import BaromeError, ContactRequiredError


@pytest.fixture
def no_contact(monkeypatch):
    monkeypatch.delenv(config.CONTACT_ENV, raising=False)


def test_there_is_no_default_contact(no_contact):
    with pytest.raises(ContactRequiredError, match="BAROME_CONTACT"):
        config.contact_email()


def test_the_env_var_supplies_the_contact(monkeypatch):
    monkeypatch.setenv(config.CONTACT_ENV, " me@clinic.org ")
    assert config.contact_email() == "me@clinic.org"
    assert config.user_agent().endswith("(me@clinic.org)")


def test_set_contact_beats_the_env_var(monkeypatch):
    monkeypatch.setenv(config.CONTACT_ENV, "env@clinic.org")
    config.set_contact("script@clinic.org")
    assert config.contact_email() == "script@clinic.org"


@pytest.mark.parametrize("bad", ["me", "me@clinic", "two words@clinic.org", ""])
def test_a_contact_that_is_not_an_email_is_refused(bad):
    with pytest.raises(ContactRequiredError, match="not an email"):
        config.set_contact(bad)


def test_a_malformed_env_contact_is_refused_not_sent(monkeypatch):
    monkeypatch.setenv(config.CONTACT_ENV, "nobody")
    with pytest.raises(ContactRequiredError, match="not an email"):
        config.contact_email()


def test_no_request_is_sent_without_a_contact(no_contact, monkeypatch):
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda *a, **k: pytest.fail("sent"))
    with pytest.raises(ContactRequiredError):
        net.get_json("https://example.invalid/x")


def test_the_lookup_fails_up_front_without_a_contact(no_contact, monkeypatch):
    monkeypatch.setattr(service.geocode_mod, "geocode", lambda *a: pytest.fail("geocoded"))
    with pytest.raises(ContactRequiredError):
        service.pressure_for_address("123 Main St, Doylestown PA 18901")
    with pytest.raises(ContactRequiredError):
        service.suggest_addresses("123 Main St")


def test_a_missing_contact_is_not_reported_as_an_unreachable_geocoder(no_contact):
    """geopy failures are wrapped as 'could not be reached'; this one must not be."""
    with pytest.raises(ContactRequiredError):
        geocode.geocode_nominatim("Rua Augusta 100, Lisboa")
    with pytest.raises(ContactRequiredError):
        geocode.geocode_photon("Rua Augusta 100, Lisboa")


# --- CLI ------------------------------------------------------------------


def test_cli_refuses_to_run_unattended_without_a_contact(no_contact, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))  # not a terminal
    assert cli.main(["123 Main St, Doylestown PA 18901"]) == 2
    assert "BAROME_CONTACT" in capsys.readouterr().err


def test_cli_rejects_a_bad_contact_flag(monkeypatch, capsys):
    assert cli.main(["--contact", "nobody", "123 Main St"]) == 2
    assert "not an email" in capsys.readouterr().err


def test_cli_contact_flag_is_used_for_the_run(no_contact, monkeypatch):
    def lookup(address, **kw):
        assert config.contact_email() == "flag@clinic.org"
        raise BaromeError("stop here")

    monkeypatch.setattr(service, "pressure_for_address", lookup)
    assert cli.main(["--contact", "flag@clinic.org", "123 Main St"]) == 1


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_cli_asks_for_a_contact_at_a_terminal(no_contact, monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda prompt: " typed@clinic.org ")
    assert cli._ensure_contact(None)
    assert config.contact_email() == "typed@clinic.org"


def test_cli_explains_a_missing_contact_when_stdin_is_nul(no_contact, monkeypatch, capsys):
    """Windows reports NUL as a terminal; EOF there must not read as 'Cancelled'."""
    monkeypatch.setattr(cli.sys, "stdin", _Tty())

    def eof(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert not cli._ensure_contact(None)
    assert "BAROME_CONTACT" in capsys.readouterr().err
