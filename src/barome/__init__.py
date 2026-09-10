"""barome - elevation-adjusted local pressure and Ctp from a single address.

The user types one thing, their address. Latitude/longitude, the weather
station, and the elevation *at that address* are all resolved for them.

    from barome import pressure_for_address, set_contact
    set_contact("you@example.org")      # or set BAROME_CONTACT
    result = pressure_for_address("123 Main St, Doylestown PA 18901")
    print(result.pressure_station_mmhg)
"""

from .config import VERSION as __version__
from .config import set_contact
from .errors import (
    AllProvidersFailedError,
    BaromeError,
    ContactRequiredError,
    ElevationError,
    GeocodingError,
    PhysicsInputError,
    ProviderError,
)
from .geocode import suggest
from .models import (
    CtpResult,
    IntercomparisonResult,
    Location,
    Observation,
    PressureResult,
    Station,
    TraceStep,
)
from .physics import CtpProtocol, Method
from .service import compare_local, ctp_for, pressure_for_address

__all__ = [
    "__version__",
    "set_contact",
    "pressure_for_address",
    "suggest",
    "ctp_for",
    "compare_local",
    "PressureResult",
    "CtpResult",
    "IntercomparisonResult",
    "Location",
    "Observation",
    "Station",
    "TraceStep",
    "CtpProtocol",
    "Method",
    "BaromeError",
    "ContactRequiredError",
    "GeocodingError",
    "ElevationError",
    "ProviderError",
    "AllProvidersFailedError",
    "PhysicsInputError",
]
