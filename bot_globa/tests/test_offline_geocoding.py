"""The birth place resolves from a bundled table, and never leaves the process."""

import gzip
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.deployment import validate_production_providers
from app.providers.geocoding.factory import create_geocoding_client
from app.providers.geocoding.offline import DATASET, OfflineGeocodingClient


def _client() -> OfflineGeocodingClient:
    return OfflineGeocodingClient()


async def test_the_cities_the_stub_could_not_answer_now_resolve() -> None:
    """Both cities a real user typed on the first day were missing from the old table."""

    for query, expected, zone in (
        ("Тюмень", "Тюмень, Россия", "Asia/Yekaterinburg"),
        ("Ноябрьск", "Ноябрьск, Россия", "Asia/Yekaterinburg"),
    ):
        found = await _client().search(query, limit=5)

        assert found, query
        assert found[0].label == expected
        assert found[0].timezone == zone


async def test_a_place_carries_everything_the_chart_needs() -> None:
    found = await _client().search("Москва", limit=1)

    assert found[0].label == "Москва, Россия"
    assert round(found[0].latitude, 2) == 55.75
    assert round(found[0].longitude, 2) == 37.62
    assert found[0].timezone == "Europe/Moscow"


async def test_the_bigger_city_wins_a_shared_name() -> None:
    """Several places are called Москва; the birth place is almost certainly the capital."""

    found = await _client().search("Москва", limit=5)

    assert [place.label for place in found][:2] == ["Москва, Россия", "Москва, США"]


async def test_an_exact_name_outranks_something_that_merely_starts_alike() -> None:
    found = await _client().search("тюме", limit=5)

    assert found[0].label == "Тюмень, Россия"
    assert len(found) > 1


async def test_case_spacing_and_yo_do_not_change_the_answer() -> None:
    variants = ["Орёл", "орел", "  ОРЁЛ  "]

    labels = {(await _client().search(value, limit=1))[0].label for value in variants}

    assert len(labels) == 1


async def test_an_unknown_place_is_empty_rather_than_an_error() -> None:
    assert await _client().search("нет-такого-города-нигде", limit=5) == ()
    assert await _client().search("   ", limit=5) == ()


async def test_the_caller_never_gets_more_than_it_asked_for() -> None:
    assert len(await _client().search("нов", limit=3)) <= 3


def test_the_dataset_ships_with_the_application() -> None:
    assert DATASET.is_file()
    assert DATASET.stat().st_size < 8_000_000


def test_every_row_is_complete_enough_to_build_a_chart() -> None:
    """A row missing a timezone would fail deep inside the astrologer instead of here."""

    with gzip.open(DATASET, "rt", encoding="utf-8") as rows:
        for number, row in enumerate(rows, start=1):
            fields = row.rstrip("\n").split("\t")
            assert len(fields) == 6, number
            label, latitude, longitude, timezone, population, aliases = fields
            assert label and timezone and aliases
            assert -90 <= float(latitude) <= 90
            assert -180 <= float(longitude) <= 180
            assert int(population) >= 0


def test_the_factory_builds_the_offline_provider_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.geocoding_provider == "offline"
    assert isinstance(create_geocoding_client(settings), OfflineGeocodingClient)


def _production(**values: object) -> Settings:
    defaults: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+asyncpg://u:p@db/x",
        "telegram_bot_token": SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        "content_encryption_key": SecretStr("test-only-strong-content-key-32-bytes"),
    }
    defaults.update(values)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_production_refuses_to_start_on_a_development_stub() -> None:
    """A stub answers, so the deployment looks healthy while the product cannot work."""

    with pytest.raises(ValueError, match="GEOCODING_PROVIDER"):
        validate_production_providers(_production(geocoding_provider="stub"))


def test_production_refuses_a_stub_model_for_the_same_reason() -> None:
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        validate_production_providers(_production(llm_provider="stub"))


def test_a_stub_outside_production_stays_allowed() -> None:
    validate_production_providers(_production(app_env="local", geocoding_provider="stub"))


def test_a_missing_dataset_is_reported_rather_than_answered_wrongly(tmp_path: Path) -> None:
    absent = OfflineGeocodingClient(tmp_path / "missing.tsv.gz")

    with pytest.raises(OSError):
        import asyncio

        asyncio.run(absent.search("Москва", limit=1))
