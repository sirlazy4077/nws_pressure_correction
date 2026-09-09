"""Domain exceptions.

Kept in one module so `service.py` can catch the whole family without importing
every provider, and so nothing in the package needs a circular import to raise.
"""


class BaromeError(Exception):
    """Base class for every error this package raises deliberately."""


class PhysicsInputError(BaromeError, ValueError):
    """A value that is physically impossible, caught at the input boundary.

    Raised instead of letting a ZeroDivisionError escape from the middle of a
    calculation (plan.md bug #10). Also a ValueError, so callers that only
    guard against bad numeric input still catch it.
    """


class GeocodingError(BaromeError):
    """Every geocoder in the chain failed or returned nothing."""


class ElevationError(BaromeError):
    """Every elevation source in the chain failed or returned nothing."""


class ProviderError(BaromeError):
    """A single weather provider could not supply a sea-level pressure."""


class AllProvidersFailedError(BaromeError):
    """The primary provider and every fallback failed."""
