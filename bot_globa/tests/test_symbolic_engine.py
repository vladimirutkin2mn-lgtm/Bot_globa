"""Unit coverage for deterministic Rider-Waite-Smith Tarot selection."""

from collections import Counter
from uuid import UUID

import pytest

from app.domain.reading import SymbolOrientation
from app.domain.tarot import MAJOR_ARCANA_V1, RWS_78_V1, TarotArcana, TarotSuit, card_knowledge
from app.services.symbolic_engine import TarotSymbolicEngine, UnknownSpreadError


def test_rws_catalog_has_the_complete_78_card_structure() -> None:
    assert RWS_78_V1.version == "rws-78-v1"
    assert len(RWS_78_V1.cards) == 78
    assert len({card.code for card in RWS_78_V1.cards}) == 78

    arcana = Counter(card.arcana for card in RWS_78_V1.cards)
    assert arcana == Counter({TarotArcana.MAJOR: 22, TarotArcana.MINOR: 56})

    suits = Counter(card.suit for card in RWS_78_V1.cards if card.suit is not None)
    assert suits == Counter(dict.fromkeys(TarotSuit, 14))
    assert all(card.upright_theme and card.reversed_theme for card in RWS_78_V1.cards)
    assert all(card.symbolic_focus for card in RWS_78_V1.cards)


def test_legacy_major_arcana_catalog_remains_versioned_for_history() -> None:
    assert MAJOR_ARCANA_V1.version == "tarot-major-v1"
    assert len(MAJOR_ARCANA_V1.cards) == 22


def test_fixed_reading_has_stable_versioned_three_card_snapshot() -> None:
    engine = TarotSymbolicEngine()
    reading_id = UUID("00000000-0000-0000-0000-000000000001")

    selected = engine.draw(reading_id, "three_card_v1")

    assert engine.version == "tarot-symbolic-v2"
    assert [item.card.code for item in selected] == ["major_04", "cups_06", "swords_queen"]
    assert [item.position for item in selected] == [
        "current_influence",
        "hidden_factor",
        "next_step",
    ]
    assert [item.orientation for item in selected] == [
        SymbolOrientation.UPRIGHT,
        SymbolOrientation.REVERSED,
        SymbolOrientation.UPRIGHT,
    ]
    assert [item.ordinal for item in selected] == [0, 1, 2]
    assert all(item.catalog_version == "rws-78-v1" for item in selected)


def test_draw_supplies_application_owned_card_knowledge_to_generation() -> None:
    selected = TarotSymbolicEngine().draw(
        UUID("00000000-0000-0000-0000-000000000001"),
        "three_card_v1",
    )

    major, cups, swords = selected
    assert "tradition=Rider-Waite-Smith" in major.interpretation_theme
    assert "position_focus=" in major.interpretation_theme
    assert "orientation_meaning=" in major.interpretation_theme
    assert "suit=cups" in cups.interpretation_theme
    assert "suit_focus=" in cups.interpretation_theme
    assert "rank=06" in cups.interpretation_theme
    assert "rank_focus=" in cups.interpretation_theme
    assert "suit=swords" in swords.interpretation_theme
    assert "rank=queen" in swords.interpretation_theme


def test_reversed_card_uses_explicit_reversed_meaning_not_mechanical_inversion() -> None:
    card = next(card for card in RWS_78_V1.cards if card.code == "cups_06")

    upright = card_knowledge(card, "hidden_factor", reversed=False)
    reversed_value = card_knowledge(card, "hidden_factor", reversed=True)

    assert card.upright_theme in upright
    assert card.reversed_theme in reversed_value
    assert card.upright_theme not in reversed_value


def test_retry_and_worker_replay_return_identical_symbols() -> None:
    engine = TarotSymbolicEngine()
    reading_id = UUID("78e8d631-0249-4a12-98c0-9a8c629ab1e1")

    first = engine.draw(reading_id, "three_card_v1")
    retry = engine.draw(reading_id, "three_card_v1")

    assert retry == first
    assert [item.to_reading_symbol() for item in retry] == [
        item.to_reading_symbol() for item in first
    ]


def test_different_readings_produce_distinct_unique_draws() -> None:
    engine = TarotSymbolicEngine()
    first = engine.draw(UUID("00000000-0000-0000-0000-000000000001"), "three_card_v1")
    second = engine.draw(UUID("00000000-0000-0000-0000-000000000002"), "three_card_v1")

    assert first != second
    assert len({item.card.code for item in first}) == 3
    assert len({item.position for item in first}) == 3


def test_unknown_spread_is_rejected_before_selection() -> None:
    with pytest.raises(UnknownSpreadError, match="unknown tarot spread"):
        TarotSymbolicEngine().draw(
            UUID("00000000-0000-0000-0000-000000000001"),
            "invented_spread",
        )
