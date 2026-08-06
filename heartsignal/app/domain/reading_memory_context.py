"""Provider-neutral contracts for bounded memory context in new readings."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.oracle_memory import MemoryClaimBasis, MemoryKind, MemorySourceType


@dataclass(frozen=True, slots=True)
class ReadingMemoryContextItem:
    """One already-ranked memory entry safe to serialize as untrusted prompt data."""

    kind: MemoryKind
    claim_basis: MemoryClaimBasis
    source_type: MemorySourceType
    value: str
    confidence_milli: int
    created_at: datetime
    source_reading_created_at: datetime | None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("reading memory context value is required")
        if not 1 <= self.confidence_milli <= 1000:
            raise ValueError("reading memory confidence must be between 1 and 1000")

    def prompt_payload(self) -> dict[str, object]:
        occurred_at = self.source_reading_created_at or self.created_at
        return {
            "kind": self.kind.value,
            "claim_basis": self.claim_basis.value,
            "source_type": self.source_type.value,
            "value": self.value,
            "confidence_milli": self.confidence_milli,
            "occurred_on": occurred_at.date().isoformat(),
        }


@runtime_checkable
class MemoryPromptUsageRecorder(Protocol):
    """Record selected item identifiers without receiving memory plaintext."""

    async def record_prompt_use(
        self,
        user_id: UUID,
        memory_item_ids: Sequence[UUID],
    ) -> int: ...


class ReadingMemoryRetriever(Protocol):
    """Retrieve a bounded set without performing a second model call."""

    async def retrieve(
        self,
        user_id: UUID,
        *,
        persona_code: str,
        topic: str,
        question: str,
        context: str | None,
    ) -> tuple[ReadingMemoryContextItem, ...]: ...
