"""Geocoding boundary: parsing, failure mapping and the privacy-relevant request shape."""

import httpx
import pytest

from app.config import Settings
from app.providers.geocoding.base import (
    GeocodingAuthenticationError,
    GeocodingRateLimitError,
    GeocodingTransientError,
    GeocodingUnexpectedError,
)
from app.providers.geocoding.factory import create_geocoding_client
from app.providers.geocoding.offline import OfflineGeocodingClient
from app.providers.geocoding.opencage import OpenCageGeocodingClient
from app.providers.geocoding.stub import StubGeocodingClient


def _result(
    formatted: str = "Москва, Россия",
    latitude: float = 55.755864,
    longitude: float = 37.617698,
    timezone: str | None = "Europe/Moscow",
) -> dict[str, object]:
    annotations: dict[str, object] = {}
    if timezone is not None:
        annotations["timezone"] = {"name": timezone}
    return {
        "formatted": formatted,
        "geometry": {"lat": latitude, "lng": longitude},
        "annotations": annotations,
    }


def _client(handler: object, *, attempts: int = 2) -> OpenCageGeocodingClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return OpenCageGeocodingClient("test-key", 5.0, attempts, transport=transport)


async def test_opencage_maps_a_result_into_a_chart_ready_place() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [_result()]})

    places = await _client(handler).search("Москва", limit=5)

    assert len(places) == 1
    assert places[0].timezone == "Europe/Moscow"
    assert places[0].latitude == pytest.approx(55.755864)
    assert captured[0].url.params["no_record"] == "1"


async def test_opencage_skips_a_result_without_a_timezone() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"results": [_result(timezone=None), _result()]})

    places = await _client(handler).search("Москва", limit=5)

    assert len(places) == 1


async def test_opencage_never_returns_more_than_the_requested_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"results": [_result() for _ in range(9)]})

    places = await _client(handler).search("Москва", limit=3)

    assert len(places) == 3


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, GeocodingAuthenticationError),
        (402, GeocodingAuthenticationError),
        (429, GeocodingRateLimitError),
        (400, GeocodingUnexpectedError),
    ],
)
async def test_opencage_maps_status_codes_to_typed_errors(
    status: int,
    expected: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, json={})

    with pytest.raises(expected):
        await _client(handler).search("Москва", limit=5)


async def test_opencage_retries_a_server_error_then_gives_a_transient_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={})

    with pytest.raises(GeocodingTransientError):
        await _client(handler, attempts=2).search("Москва", limit=5)

    assert calls == 2


async def test_geocoding_errors_never_repeat_the_users_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(429, json={})

    with pytest.raises(GeocodingRateLimitError) as captured:
        await _client(handler).search("Приволжский переулок 4, Тверь", limit=5)

    assert "Тверь" not in str(captured.value)


async def test_stub_prefers_a_prefix_match_and_ignores_case_and_yo() -> None:
    stub = StubGeocodingClient()

    prefixed = await stub.search("моск", limit=5)
    with_yo = await stub.search("КИШИНЁВ", limit=5)

    assert prefixed[0].label.startswith("Москва")
    assert with_yo and with_yo[0].timezone == "Europe/Chisinau"


async def test_stub_returns_nothing_for_an_unknown_place() -> None:
    assert await StubGeocodingClient().search("несуществующий-город", limit=5) == ()


def test_factory_builds_the_bundled_directory_by_default(settings: Settings) -> None:
    """Production must never fall back to the 44-city development table by accident."""

    assert isinstance(create_geocoding_client(settings), OfflineGeocodingClient)


def test_the_development_stub_is_still_available_when_asked_for(settings: Settings) -> None:
    configured = settings.model_copy(update={"geocoding_provider": "stub"})

    assert isinstance(create_geocoding_client(configured), StubGeocodingClient)


def test_factory_refuses_opencage_without_a_key(settings: Settings) -> None:
    configured = settings.model_copy(update={"geocoding_provider": "opencage"})

    with pytest.raises(ValueError, match="GEOCODING_API_KEY"):
        create_geocoding_client(configured)
