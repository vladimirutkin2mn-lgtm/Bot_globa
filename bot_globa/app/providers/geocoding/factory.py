"""Validated geocoding provider construction."""

from app.config import Settings
from app.providers.geocoding.base import GeocodingClient
from app.providers.geocoding.offline import OfflineGeocodingClient
from app.providers.geocoding.opencage import OpenCageGeocodingClient
from app.providers.geocoding.stub import StubGeocodingClient


def create_geocoding_client(settings: Settings) -> GeocodingClient:
    if settings.geocoding_provider == "offline":
        return OfflineGeocodingClient()
    if settings.geocoding_provider == "stub":
        return StubGeocodingClient()
    if settings.geocoding_provider == "opencage":
        key = settings.geocoding_api_key.get_secret_value().strip()
        if not key:
            raise ValueError("GEOCODING_API_KEY is required for the opencage provider")
        return OpenCageGeocodingClient(
            key,
            settings.geocoding_timeout_seconds,
            settings.geocoding_max_transport_attempts,
        )
    raise ValueError(f"Unsupported geocoding provider: {settings.geocoding_provider!r}")
