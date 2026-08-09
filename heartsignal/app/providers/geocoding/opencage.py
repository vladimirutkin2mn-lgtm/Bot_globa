"""OpenCage adapter: one call returns coordinates and the IANA timezone.

`no_record=1` asks OpenCage not to retain the query. Nothing here logs the query, the
resolved label or the coordinates — a birth place is consent-gated sensitive content.
"""

import httpx

from app.providers.geocoding.base import (
    GeocodedPlace,
    GeocodingAuthenticationError,
    GeocodingRateLimitError,
    GeocodingTimeoutError,
    GeocodingTransientError,
    GeocodingUnexpectedError,
)

_ENDPOINT = "https://api.opencagedata.com/geocode/v1/json"
_AUTH_STATUSES = frozenset({401, 402, 403})
_RATE_LIMIT_STATUS = 429
_CLIENT_ERROR_FLOOR = 400
_SERVER_ERROR_FLOOR = 500


class OpenCageGeocodingClient:
    """Resolve a free-text place into candidates the astrology engine can use."""

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float,
        max_transport_attempts: int,
        language: str = "ru",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self._language = language
        self._attempts = max_transport_attempts
        self._client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def search(self, query: str, *, limit: int) -> tuple[GeocodedPlace, ...]:
        payload = await self._request(query, limit)
        results = payload.get("results")
        if not isinstance(results, list):
            raise GeocodingUnexpectedError("geocoding response has no results array")
        places: list[GeocodedPlace] = []
        for entry in results[:limit]:
            place = _place_from(entry)
            if place is not None:
                places.append(place)
        return tuple(places)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, query: str, limit: int) -> dict[str, object]:
        parameters = {
            "q": query,
            "key": self._key,
            "limit": str(limit),
            "language": self._language,
            "no_record": "1",
            "abbrv": "1",
        }
        last_error: Exception | None = None
        for _ in range(self._attempts):
            try:
                response = await self._client.get(_ENDPOINT, params=parameters)
            except httpx.TimeoutException as error:
                last_error = GeocodingTimeoutError("geocoding request timed out")
                last_error.__cause__ = error
                continue
            except httpx.HTTPError as error:
                last_error = GeocodingTransientError("geocoding transport failed")
                last_error.__cause__ = error
                continue
            if response.status_code in _AUTH_STATUSES:
                raise GeocodingAuthenticationError("geocoding credentials rejected")
            if response.status_code == _RATE_LIMIT_STATUS:
                raise GeocodingRateLimitError("geocoding rate limit reached")
            if response.status_code >= _SERVER_ERROR_FLOOR:
                last_error = GeocodingTransientError("geocoding provider is unavailable")
                continue
            if response.status_code >= _CLIENT_ERROR_FLOOR:
                raise GeocodingUnexpectedError("geocoding request was rejected")
            try:
                decoded = response.json()
            except ValueError as error:
                raise GeocodingUnexpectedError("geocoding response is not JSON") from error
            if not isinstance(decoded, dict):
                raise GeocodingUnexpectedError("geocoding response has an unexpected shape")
            return decoded
        raise last_error or GeocodingUnexpectedError("geocoding request failed")


def _place_from(entry: object) -> GeocodedPlace | None:
    """Skip a result that cannot produce a complete, chart-ready place."""
    if not isinstance(entry, dict):
        return None
    label = entry.get("formatted")
    geometry = entry.get("geometry")
    annotations = entry.get("annotations")
    if not isinstance(label, str) or not isinstance(geometry, dict):
        return None
    latitude = geometry.get("lat")
    longitude = geometry.get("lng")
    timezone = None
    if isinstance(annotations, dict):
        zone = annotations.get("timezone")
        if isinstance(zone, dict) and isinstance(zone.get("name"), str):
            timezone = zone["name"]
    if timezone is None:
        return None
    if isinstance(latitude, bool) or not isinstance(latitude, int | float):
        return None
    if isinstance(longitude, bool) or not isinstance(longitude, int | float):
        return None
    try:
        return GeocodedPlace(
            label=label[:200],
            latitude=float(latitude),
            longitude=float(longitude),
            timezone=timezone,
        )
    except ValueError:
        return None
