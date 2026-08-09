"""Clean geocoding boundary with no vendor types.

A birth place is sensitive content: it is consent-gated and encrypted at rest. An
implementation may send the user's query to a third party, so it must never log the
query, the resolved label or the coordinates.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

MAX_PLACE_QUERY_LENGTH = 200
MAX_PLACE_CANDIDATES = 5


@dataclass(frozen=True, slots=True)
class GeocodedPlace:
    """One resolved birth place, complete enough to build a `BirthProfileInput`."""

    label: str
    latitude: float
    longitude: float
    timezone: str

    def __post_init__(self) -> None:
        if not self.label.strip() or len(self.label) > MAX_PLACE_QUERY_LENGTH:
            raise ValueError("geocoded place label is out of range")
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("geocoded latitude must be between -90 and 90")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("geocoded longitude must be between -180 and 180")
        if not self.timezone.strip():
            raise ValueError("geocoded place requires an IANA timezone")


class GeocodingClient(Protocol):
    async def search(self, query: str, *, limit: int) -> tuple[GeocodedPlace, ...]:
        """Return at most `limit` candidates, best match first, possibly empty."""
        ...


@runtime_checkable
class ClosableGeocodingClient(Protocol):
    async def aclose(self) -> None: ...


async def close_geocoding_client(client: GeocodingClient) -> None:
    """Close lifecycle-aware providers; plain protocol implementations need no close."""
    if isinstance(client, ClosableGeocodingClient):
        await client.aclose()


class GeocodingError(Exception):
    """Base error carrying no part of the user's query."""


class GeocodingTimeoutError(GeocodingError):
    pass


class GeocodingRateLimitError(GeocodingError):
    pass


class GeocodingAuthenticationError(GeocodingError):
    pass


class GeocodingTransientError(GeocodingError):
    pass


class GeocodingUnexpectedError(GeocodingError):
    pass
