"""Unit coverage for Reading validation and state transitions."""

import pytest
from pydantic import ValidationError

from app.domain.reading import (
    InvalidReadingTransition,
    ReadingDraftRequest,
    ReadingStatus,
    ReadingSymbolInput,
    SymbolOrientation,
    ensure_reading_transition,
)


def test_reading_draft_request_is_strict_and_normalized() -> None:
    request = ReadingDraftRequest(
        persona_code="tarot_reader",
        topic="decision",
        question="  Что мне сейчас важно увидеть?  ",
        context="I cannot choose between two options",
        engine_version="reading-v1",
        prompt_version="tarot-v1",
        schema_version="reading-result-v1",
        cost_units=1,
    )

    assert request.question == "Что мне сейчас важно увидеть?"
    assert request.persona_code == "tarot_reader"


def test_reading_draft_rejects_unsafe_codes_and_negative_cost() -> None:
    with pytest.raises(ValidationError):
        ReadingDraftRequest(
            persona_code="Tarot Reader",
            topic="decision",
            question="Question",
            engine_version="v1",
            prompt_version="v1",
            schema_version="v1",
            cost_units=-1,
        )


def test_reading_state_machine_allows_only_explicit_transitions() -> None:
    ensure_reading_transition(ReadingStatus.DRAFT, ReadingStatus.GENERATING)
    ensure_reading_transition(ReadingStatus.GENERATING, ReadingStatus.PREVIEW_READY)
    ensure_reading_transition(ReadingStatus.PREVIEW_READY, ReadingStatus.FULL_READY)
    ensure_reading_transition(ReadingStatus.FULL_READY, ReadingStatus.DELETED)

    with pytest.raises(InvalidReadingTransition):
        ensure_reading_transition(ReadingStatus.DRAFT, ReadingStatus.FULL_READY)
    with pytest.raises(InvalidReadingTransition):
        ensure_reading_transition(ReadingStatus.DELETED, ReadingStatus.GENERATING)


def test_symbol_input_has_closed_orientation_contract() -> None:
    symbol = ReadingSymbolInput(
        symbol_id="major_02",
        position="current_influence",
        orientation=SymbolOrientation.REVERSED,
        catalog_version="tarot-v1",
    )

    assert symbol.orientation is SymbolOrientation.REVERSED
    with pytest.raises(ValidationError):
        ReadingSymbolInput(
            symbol_id="major_02",
            position="current influence",
            orientation="sideways",  # type: ignore[arg-type]
            catalog_version="tarot-v1",
        )
