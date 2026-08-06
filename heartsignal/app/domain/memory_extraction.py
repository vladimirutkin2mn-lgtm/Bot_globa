"""Contracts for extracting consented memory from completed oracle readings."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryKind,
    MemoryValue,
    StrictMemoryModel,
    VersionCode,
)

CURRENT_MEMORY_EXTRACTION_VERSION = "oracle-memory-extractor-v1"


class MemoryExtractionCandidate(StrictMemoryModel):
    """One durable memory candidate without topic-based censorship."""

    kind: MemoryKind
    value: MemoryValue
    confidence_milli: int = Field(ge=1, le=1000)
    claim_basis: MemoryClaimBasis


class MemoryExtractionPayload(StrictMemoryModel):
    candidates: list[MemoryExtractionCandidate] = Field(max_length=12)


@dataclass(frozen=True, slots=True)
class CompletedReadingMemorySnapshot:
    reading_id: UUID
    persona_code: str
    topic: str
    question: str
    context: str | None
    result: dict[str, object]


class MemoryExtractionStatus(StrEnum):
    COMPLETED = "completed"
    NO_CANDIDATES = "no_candidates"


@dataclass(frozen=True, slots=True)
class MemoryExtractionOutcome:
    status: MemoryExtractionStatus
    extraction_version: VersionCode
    created_count: int
    skipped_count: int
