"""The deck is an asset: complete when installed, harmless when absent."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.bot import tarot_art
from app.bot.tarot_art import TAROT_ASSET_DIR, card_art, deck_is_installed
from app.domain.tarot import MAJOR_ARCANA_V1

MAX_CARD_BYTES = 1_000_000


@pytest.fixture(autouse=True)
def _clean_lookup_cache() -> Iterator[None]:
    card_art.cache_clear()
    yield
    card_art.cache_clear()


def test_the_deck_covers_every_card_the_engine_can_draw() -> None:
    """A missing file is a card the reveal silently downgrades — catch it here instead."""

    installed = {path.stem for path in TAROT_ASSET_DIR.glob("major_*.jpg")}

    assert installed == {card.code for card in MAJOR_ARCANA_V1.cards}


def test_the_deck_carries_nothing_the_engine_cannot_draw() -> None:
    codes = {card.code for card in MAJOR_ARCANA_V1.cards}

    assert all(path.stem in codes for path in TAROT_ASSET_DIR.glob("*.jpg"))


def test_every_card_stays_inside_the_telegram_upload_budget() -> None:
    oversized = [
        path.name
        for path in TAROT_ASSET_DIR.glob("major_*.jpg")
        if path.stat().st_size >= MAX_CARD_BYTES
    ]

    assert oversized == []


def test_a_card_resolves_to_art_keyed_apart_from_the_scenes() -> None:
    """Scene keys and card keys share one `file_id` cache, so they may not collide."""

    art = card_art("major_13")

    assert art is not None
    assert art.key == "tarot:major_13"
    assert art.path.name == "major_13.jpg"


def test_an_unknown_card_is_absent_rather_than_an_error() -> None:
    assert card_art("major_99") is None


def test_a_deck_that_is_not_installed_simply_answers_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a deck the reveal keeps the waiting illustration; nothing may raise."""

    monkeypatch.setattr(tarot_art, "TAROT_ASSET_DIR", tmp_path)
    card_art.cache_clear()

    assert card_art("major_00") is None
    assert not deck_is_installed()
