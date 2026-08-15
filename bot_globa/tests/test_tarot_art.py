"""The visual Tarot deck must resolve every card the RWS engine can draw."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.bot import tarot_art
from app.bot.tarot_art import RWS_ART_REVISION, TAROT_ASSET_DIR, card_art, deck_is_installed
from app.domain.tarot import RWS_78_V1, TarotArcana

MAX_CARD_BYTES = 1_000_000


@pytest.fixture(autouse=True)
def _clean_lookup_cache() -> Iterator[None]:
    card_art.cache_clear()
    yield
    card_art.cache_clear()


def test_visual_deck_covers_every_card_the_engine_can_draw() -> None:
    missing = [card.code for card in RWS_78_V1.cards if card_art(card.code) is None]

    assert missing == []


def test_local_deck_contains_only_the_bespoke_major_arcana() -> None:
    expected = {card.code for card in RWS_78_V1.cards if card.arcana is TarotArcana.MAJOR}
    installed = {path.stem for path in TAROT_ASSET_DIR.glob("*.jpg")}

    assert installed == expected


def test_every_local_major_stays_inside_the_telegram_upload_budget() -> None:
    oversized = [
        path.name
        for path in TAROT_ASSET_DIR.glob("major_*.jpg")
        if path.stat().st_size >= MAX_CARD_BYTES
    ]

    assert oversized == []


def test_a_local_major_resolves_to_art_keyed_apart_from_scenes() -> None:
    art = card_art("major_13")

    assert art is not None
    assert art.key == "tarot:major_13"
    assert isinstance(art.path, Path)
    assert art.path.name == "major_13.jpg"


def test_minor_arcana_resolve_to_pinned_rws_images() -> None:
    cups = card_art("cups_06")
    swords = card_art("swords_queen")
    pentacles = card_art("pentacles_king")
    wands = card_art("wands_page")

    assert cups is not None and isinstance(cups.path, str)
    assert swords is not None and isinstance(swords.path, str)
    assert pentacles is not None and isinstance(pentacles.path, str)
    assert wands is not None and isinstance(wands.path, str)
    assert f"/{RWS_ART_REVISION}/" in cups.path
    assert cups.path.endswith("/Cups06.jpg")
    assert swords.path.endswith("/Swords13.jpg")
    assert pentacles.path.endswith("/Pents14.jpg")
    assert wands.path.endswith("/Wands11.jpg")
    assert "/main/" not in cups.path


def test_an_unknown_card_is_absent_rather_than_becoming_an_external_url() -> None:
    assert card_art("major_99") is None
    assert card_art("cups_99") is None
    assert card_art("https://example.com/card.jpg") is None


def test_missing_local_major_degrades_without_disabling_remote_minors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tarot_art, "TAROT_ASSET_DIR", tmp_path)
    card_art.cache_clear()

    assert card_art("major_00") is None
    assert card_art("cups_02") is not None
    assert not deck_is_installed()
