"""Topic-specific Tarot layouts are explicit, versioned and deterministic."""

from uuid import UUID

import pytest

from app.domain.tarot_spreads import POSITION_FOCUS, TOPIC_SPREADS, spread_for_topic, tarot_spread
from app.services.symbolic_engine import TarotSymbolDrawer, UnknownSpreadError

READING_ID = UUID("11111111-2222-3333-4444-555555555555")


def test_every_tarot_topic_has_its_own_versioned_five_card_layout() -> None:
    assert set(TOPIC_SPREADS) == {
        "love",
        "work",
        "decision",
        "repeating_pattern",
        "general_forecast",
    }
    assert len({spread.code for spread in TOPIC_SPREADS.values()}) == len(TOPIC_SPREADS)
    for topic, spread in TOPIC_SPREADS.items():
        assert spread_for_topic(topic) is spread
        assert tarot_spread(spread.code) is spread
        assert spread.code.endswith("_v1")
        assert len(spread.positions) == 5
        assert len(set(spread.positions)) == 5
        assert all(position in POSITION_FOCUS for position in spread.positions)


def test_topic_router_selects_the_expected_product_layouts() -> None:
    drawer = TarotSymbolDrawer()

    assert drawer.set_code_for_topic("love") == "relationship_five_v1"
    assert drawer.set_code_for_topic("work") == "work_five_v1"
    assert drawer.set_code_for_topic("decision") == "decision_five_v1"
    assert drawer.set_code_for_topic("repeating_pattern") == "pattern_five_v1"
    assert drawer.set_code_for_topic("general_forecast") == "open_question_five_v1"


def test_unknown_topic_cannot_silently_fall_back_to_a_generic_layout() -> None:
    with pytest.raises(UnknownSpreadError, match="no tarot spread for topic"):
        TarotSymbolDrawer().set_code_for_topic("unknown_topic")


def test_persisted_set_code_controls_positions_and_seed_independently_of_topic_router() -> None:
    drawer = TarotSymbolDrawer()

    decision = drawer.draw(READING_ID, "decision_five_v1")
    relationship = drawer.draw(READING_ID, "relationship_five_v1")
    replay = drawer.draw(READING_ID, "decision_five_v1")

    assert decision == replay
    assert tuple(item.symbol.position for item in decision) == TOPIC_SPREADS["decision"].positions
    assert tuple(item.symbol.position for item in relationship) == TOPIC_SPREADS["love"].positions
    assert tuple(item.symbol.symbol_id for item in decision) != tuple(
        item.symbol.symbol_id for item in relationship
    )


def test_position_context_is_product_owned_but_card_meaning_remains_rws() -> None:
    first = TarotSymbolDrawer().draw(READING_ID, "relationship_five_v1")[0]

    assert "tradition=Rider-Waite-Smith" in first.interpretation_theme
    assert f"position_focus={POSITION_FOCUS['relationship_dynamic']}" in first.interpretation_theme
    assert "position_focus=relationship_dynamic" not in first.interpretation_theme


def test_relationship_layout_does_not_turn_an_unspoken_factor_into_mind_reading() -> None:
    assert "без утверждений о чужих мыслях" in POSITION_FOCUS["unspoken_factor"]
