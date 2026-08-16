"""The visual Tarot deck must resolve every card the RWS engine can draw."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.bot import tarot_art
from app.bot.tarot_art import TAROT_ASSET_DIR, card_art, deck_is_installed
from app.domain.tarot import RWS_78_V1

MAX_CARD_BYTES = 1_000_000


@pytest.fixture(autouse=True)
def _clean_lookup_cache() -> Iterator[None]:
    card_art.cache_clear()
    yield
    card_art.cache_clear()


def test_visual_deck_covers_every_card_the_engine_can_draw() -> None:
    missing = [card.code for card in RWS_78_V1.cards if card_art(card.code) is None]

    assert missing == []


def test_bundled_deck_matches_the_catalogue_exactly() -> None:
    expected = {card.code for card in RWS_78_V1.cards}
    installed = {path.stem for path in TAROT_ASSET_DIR.glob("*.jpg")}

    assert installed == expected


def test_every_bundled_card_stays_inside_the_telegram_upload_budget() -> None:
    oversized = [
        path.name for path in TAROT_ASSET_DIR.glob("*.jpg") if path.stat().st_size >= MAX_CARD_BYTES
    ]

    assert oversized == []


def test_a_card_resolves_to_a_local_path_keyed_apart_from_scenes() -> None:
    art = card_art("major_13")

    assert art is not None
    assert art.key == "tarot:major_13"
    assert isinstance(art.path, Path)
    assert art.path.name == "major_13.jpg"


def test_minor_arcana_resolve_to_their_own_bundled_files() -> None:
    for code, filename in (
        ("cups_06", "cups_06.jpg"),
        ("swords_queen", "swords_queen.jpg"),
        ("pentacles_king", "pentacles_king.jpg"),
        ("wands_page", "wands_page.jpg"),
    ):
        art = card_art(code)

        assert art is not None, code
        assert art.key == f"tarot:{code}"
        assert art.path.parent == TAROT_ASSET_DIR
        assert art.path.name == filename


def test_an_unknown_card_is_absent_rather_than_becoming_a_file_lookup() -> None:
    assert card_art("major_99") is None
    assert card_art("cups_99") is None
    assert card_art("https://example.com/card.jpg") is None
    assert card_art("../../../etc/passwd") is None


def test_a_missing_deck_degrades_to_the_scene_illustration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tarot_art, "TAROT_ASSET_DIR", tmp_path)
    card_art.cache_clear()

    assert card_art("major_00") is None
    assert card_art("cups_02") is None
    assert not deck_is_installed()
