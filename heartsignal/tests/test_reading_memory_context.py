"""Bounded deterministic retrieval for new reading prompts."""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryItemView,
    MemoryKind,
    MemorySourceType,
)
from app.services.oracle_memory import OracleMemoryService
from app.services.reading_memory_context import OracleReadingMemoryRetriever


class FakeMemoryService:
    def __init__(self, items: list[MemoryItemView]) -> None:
        self.items = items
        self.user_ids: list[UUID] = []

    async def list_active(self, user_id: UUID) -> list[MemoryItemView]:
        self.user_ids.append(user_id)
        return list(self.items)


def _item(
    value: str,
    *,
    kind: MemoryKind,
    claim_basis: MemoryClaimBasis,
    confidence: int,
    age_days: int,
) -> MemoryItemView:
    created_at = datetime(2026, 8, 6, tzinfo=UTC) - timedelta(days=age_days)
    reading_derived = claim_basis is MemoryClaimBasis.MODEL_INFERRED
    return MemoryItemView(
        id=uuid4(),
        kind=kind,
        value=value,
        confidence_milli=confidence,
        claim_basis=claim_basis,
        source_type=(
            MemorySourceType.READING_DERIVED
            if reading_derived
            else MemorySourceType.USER_EXPLICIT
        ),
        source_reading_id=uuid4() if reading_derived else None,
        source_reading_created_at=created_at if reading_derived else None,
        source_persona_code="tarot_reader" if reading_derived else None,
        extraction_version="test-v1",
        candidate_key="candidate-v1" if reading_derived else None,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_retrieval_preserves_high_stakes_topics_and_epistemic_labels() -> None:
    user_id = uuid4()
    relationship = _item(
        "I am deciding whether to leave a controlling relationship after an abuse crisis",
        kind=MemoryKind.RELATIONSHIP_NOTES,
        claim_basis=MemoryClaimBasis.USER_STATED,
        confidence=950,
        age_days=1,
    )
    inferred = _item(
        "The user may fear repeating the same relationship pattern",
        kind=MemoryKind.RECURRING_THEME,
        claim_basis=MemoryClaimBasis.MODEL_INFERRED,
        confidence=700,
        age_days=0,
    )
    financial = _item(
        "My lawyer mentioned bankruptcy while I was discussing financial stress",
        kind=MemoryKind.USER_STATEMENT,
        claim_basis=MemoryClaimBasis.USER_STATED,
        confidence=900,
        age_days=2,
    )
    irrelevant = _item(
        "I prefer dark interface themes",
        kind=MemoryKind.USER_STATEMENT,
        claim_basis=MemoryClaimBasis.USER_STATED,
        confidence=1000,
        age_days=0,
    )
    fake = FakeMemoryService([irrelevant, financial, inferred, relationship])
    retriever = OracleReadingMemoryRetriever(cast(OracleMemoryService, fake))

    selected = await retriever.retrieve(
        user_id,
        persona_code="tarot_reader",
        topic="love",
        question="Why do I repeat this relationship pattern and should I leave?",
        context="I need reflection about the current relationship crisis",
    )

    assert fake.user_ids == [user_id]
    values = [item.value for item in selected]
    assert relationship.value in values
    assert inferred.value in values
    assert irrelevant.value not in values
    assert selected[values.index(inferred.value)].claim_basis is MemoryClaimBasis.MODEL_INFERRED
    assert "abuse crisis" in relationship.value
    # No topic blacklist exists: a matching legal/financial statement remains eligible.
    financial_selected = await retriever.retrieve(
        user_id,
        persona_code="tarot_reader",
        topic="decision",
        question="How should I reflect on bankruptcy and financial stress?",
        context="My lawyer was part of this conversation",
    )
    assert financial.value in [item.value for item in financial_selected]


@pytest.mark.asyncio
async def test_retrieval_enforces_item_and_character_budgets() -> None:
    items = [
        _item(
            f"career goal {index} " + "x" * 300,
            kind=MemoryKind.PERSONAL_GOAL,
            claim_basis=MemoryClaimBasis.USER_STATED,
            confidence=900 - index,
            age_days=index,
        )
        for index in range(10)
    ]
    retriever = OracleReadingMemoryRetriever(
        cast(OracleMemoryService, FakeMemoryService(items)),
        max_items=3,
        max_item_characters=80,
        max_total_characters=170,
    )

    selected = await retriever.retrieve(
        uuid4(),
        persona_code="tarot_reader",
        topic="work",
        question="What matters for my career goal?",
        context=None,
    )

    assert 1 <= len(selected) <= 3
    assert all(len(item.value) <= 80 for item in selected)
    assert sum(len(item.value) for item in selected) <= 170
    assert all(item.value.endswith("…") for item in selected)


@pytest.mark.asyncio
async def test_retrieval_returns_empty_when_consent_service_returns_no_memory() -> None:
    retriever = OracleReadingMemoryRetriever(
        cast(OracleMemoryService, FakeMemoryService([]))
    )
    assert (
        await retriever.retrieve(
            uuid4(),
            persona_code="tarot_reader",
            topic="general_forecast",
            question="What should I reflect on?",
            context=None,
        )
        == ()
    )
