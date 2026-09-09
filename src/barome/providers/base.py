"""The provider contract.

**Every provider's only job is to return P_msl** (sea-level-adjusted pressure)
plus metadata about where it came from. None of them does the elevation
correction: that is provider-independent and happens once, in physics.py,
against the user's own elevation.

That is what keeps the trace identical in shape no matter which source
answered, and means adding a fourth provider later never touches the maths.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Observation


class PressureProvider(Protocol):
    name: str

    def fetch(self, lat: float, lon: float) -> Observation:
        """Return the current sea-level pressure near (lat, lon).

        Raises ProviderError if it cannot, so the chain in service.py has one
        exception type to catch before falling through to the next provider.
        """
        ...


def us_only(provider_name: str) -> bool:
    return provider_name == "nws"
