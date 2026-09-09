"""TLS trust and the single HTTP helper. No network."""

import ssl
import urllib.error

import pytest

from barome import net


@pytest.fixture(autouse=True)
def _clear_context_cache():
    net.ssl_context.cache_clear()
    yield
    net.ssl_context.cache_clear()


def test_system_trust_is_used_when_truststore_is_installed():
    pytest.importorskip("truststore")
    assert net.using_system_trust() is True
    assert isinstance(net.ssl_context(), ssl.SSLContext)


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_system_trust_can_be_switched_off(monkeypatch, value):
    monkeypatch.setenv(net.TRUST_ENV, value)
    assert net.ssl_context() is None
    assert net.using_system_trust() is False


def test_no_truststore_falls_back_to_pythons_default(monkeypatch):
    """None means 'use Python's default context', not 'skip verification'."""
    import builtins

    real_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "truststore":
            raise ImportError("no truststore here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    assert net.ssl_context() is None


def test_certificate_advice_names_the_fix_when_trust_is_not_wired(monkeypatch):
    monkeypatch.setenv(net.TRUST_ENV, "0")
    advice = net.certificate_advice()
    assert "pip install truststore" in advice


def test_certificate_advice_stops_blaming_the_client_once_trust_is_wired():
    """If the OS store already rejects it, telling the user to install
    truststore sends them down a dead end."""
    pytest.importorskip("truststore")
    advice = net.certificate_advice()
    assert "pip install truststore" not in advice
    assert "proxy" in advice


def test_a_tls_failure_surfaces_as_advice_not_a_stack_trace(monkeypatch):
    def boom(*args, **kwargs):
        raise urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))

    monkeypatch.setattr(net.urllib.request, "urlopen", boom)
    with pytest.raises(net.HttpError) as caught:
        net.get_json("https://example.invalid/x")
    assert "TLS certificate rejected" in str(caught.value)


def test_an_ordinary_network_failure_still_names_the_url(monkeypatch):
    def boom(*args, **kwargs):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(net.urllib.request, "urlopen", boom)
    with pytest.raises(net.HttpError, match="example.invalid"):
        net.get_json("https://example.invalid/x")


def test_build_url_drops_none_parameters():
    url = net.build_url("https://x/y", {"a": 1, "b": None, "c": "two words"})
    assert url == "https://x/y?a=1&c=two+words"
