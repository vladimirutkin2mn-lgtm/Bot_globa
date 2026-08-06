"""Usage telemetry must never block bounded memory retrieval."""

import logging
from datetime import UTC, datetime
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


class FailingUsageMemoryService:
    def __init__(self, item: MemoryItemView) -> None:
        self.item = item
        self.recorded_ids: list[UUID] = []

    async def list_active(self, user_id: UUID) -> list[MemoryItemView]:
        return [self.item]

    async def record_prompt_use(self, user_id: UUID, memory_item_ids: list[UUID]) -> int:
        self.recorded_ids = list(memory_item_ids)
        raise RuntimeError("private-memory-storage-detail")


@pytest.mark.asyncio
async def test_usage_telemetry_failure_keeps_context_and_logs_no_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "private-relationship-memory-marker"
    item = MemoryItemView(
        id=uuid4(),
        kind=MemoryKind.RELATIONSHIP_NOTES,
        value=f"I repeat one relationship pattern {marker}",
        confidence_milli=900,
        claim_basis=MemoryClaimBasis.USER_STATED,
        source_type=MemorySourceType.USER_EXPLICIT,
        source_reading_id=None,
        source_reading_created_at=None,
        source_persona_code=None,
        extraction_version="usage-test-v1",
        candidate_key=None,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    fake = FailingUsageMemoryService(item)
    retriever = OracleReadingMemoryRetriever(cast(OracleMemoryService, fake))
    caplog.set_level(logging.WARNING)

    selected = await retriever.retrieve(
        uuid4(),
        persona_code="tarot_reader",
        topic="repeating_pattern",
        question="Why do I repeat this relationship pattern?",
        context=None,
    )

    assert [entry.value for entry in selected] == [item.value]
    assert fake.recorded_ids == [item.id]
    assert "reading_memory_usage_record_failed" in caplog.text
    assert marker not in caplog.text
    assert "private-memory-storage-detail" not in caplog.text
