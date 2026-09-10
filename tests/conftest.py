"""Shared setup: every test runs as a configured local user, offline."""

import pytest

from barome import config


@pytest.fixture(autouse=True)
def _local_user(monkeypatch, tmp_path):
    """A local run needs a contact, and caches elevation on disk. Give every
    test a contact and a private cache file, so no test depends on the
    developer's environment or writes into their real cache."""
    monkeypatch.setenv(config.CONTACT_ENV, "tests@example.com")
    monkeypatch.setenv(config.ELEVATION_CACHE_ENV, str(tmp_path / "elevation.json"))
    monkeypatch.setattr(config, "_contact_override", None)
