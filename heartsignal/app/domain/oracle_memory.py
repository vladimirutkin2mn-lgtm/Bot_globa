"""Strict contracts for consented, privacy-preserving oracle memory."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CURRENT_MEMORY_CONSENT_VERSION = "oracle-memory-v1"

VersionCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]
PersonaCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    ),
]
MemoryValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]


class StrictMemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MemoryConsentStatus(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class MemoryItemStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class MemoryKind(StrEnum):
    """Closed allow-list; high-stakes diagnoses and directives are intentionally absent."""

    USER_PREFERENCE = "user_preference"
    PERSONAL_GOAL = "personal_goal"
    RELATIONSHIP_CONTEXT = "relationship_context"
    RECURRING_THEME = "recurring_theme"
    BIRTH_PROFILE = "birth_profile"
    ORACLE_PREFERENCE = "oracle_preference"


class MemorySourceType(StrEnum):
    USER_EXPLICIT = "user_explicit"
    READING_DERIVED = "reading_derived"
    PROFILE_IMPORTED = "profile_imported"


class MemoryCreateRequest(StrictMemoryModel):
    kind: MemoryKind
    value: MemoryValue
    confidence_milli: int = Field(ge=1, le=1000)
    source_type: MemorySourceType
    source_reading_id: UUID | None = None
    source_persona_code: PersonaCode | None = None
    extraction_version: VersionCode

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.source_type is MemorySourceType.READING_DERIVED and self.source_reading_id is None:
            raise ValueError("reading-derived memory requires source_reading_id")
        if (
            self.source_type is not MemorySourceType.READING_DERIVED
            and self.source_reading_id is not None
        ):
            raise ValueError("source_reading_id is only valid for reading-derived memory")
        return self


@dataclass(frozen=True, slots=True)
class MemoryConsentView:
    status: MemoryConsentStatus
    consent_version: str
    accepted_at: datetime | None
    revoked_at: datetime | None

    @property
    def permits_memory(self) -> bool:
        return (
            self.status is MemoryConsentStatus.GRANTED
            and self.consent_version == CURRENT_MEMORY_CONSENT_VERSION
        )


@dataclass(frozen=True, slots=True)
class MemoryItemView:
    id: UUID
    kind: MemoryKind
    value: str
    confidence_milli: int
    source_type: MemorySourceType
    source_reading_id: UUID | None
    source_persona_code: str | None
    extraction_version: str
    created_at: datetime
