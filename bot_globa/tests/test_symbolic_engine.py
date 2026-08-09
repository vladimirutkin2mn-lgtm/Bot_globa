"""Unit coverage for deterministic tarot symbol selection."""

from uuid import UUID

import pytest

from app.domain.reading import SymbolOrientation
from app.services.symbolic_engine import TarotSymbolicEngine, UnknownSpreadError


def test_fixed_reading_has_stable_versioned_three_card_snapshot() -> None:
    engine = TarotSymbolicEngine()
    reading_id = UUID("00000000-0000-0000-0000-000000000001")

    selected = engine.draw(reading_id, "three_card_v1")

    assert [item.card.code for item in selected] == ["major_20", "major_07", "major_06"]
    assert [item.position for item in selected] == [
        "current_influence",
        "hidden_factor",
        "next_step",
    ]
    assert [item.orientation for item in selected] == [
        SymbolOrientation.REVERSED,
        SymbolOrientation.REVERSED,
        SymbolOrientation.REVERSED,
    ]
    assert [item.ordinal for item in selected] == [0, 1, 2]
    assert all(item.catalog_version == "tarot-major-v1" for item in selected)


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
