"""Provider-neutral contracts for generating and persisting oracle readings."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.reading import ReadingSymbolInput


class ReadingGenerationClaimStatus(StrEnum):
    CLAIMED = "claimed"
    READY = "ready"
    ALREADY_PROCESSING = "already_processing"
    NOT_READY = "not_ready"
    PERSONA_DISABLED = "persona_disabled"
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    CORRUPTED_RESULT = "corrupted_result"


class ReadingGenerationFinalizeStatus(StrEnum):
    COMPLETED = "completed"
    STATE_CONFLICT = "state_conflict"
    DELETED = "deleted"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class ReadingGenerationContext:
    reading_id: UUID
    user_id: UUID
    persona_code: str
    topic: str
    question: str
    context: str | None
    engine_version: str
    prompt_version: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class StoredReadingResult:
    payload: dict[str, object]
    symbols: tuple[ReadingSymbolInput, ...]


@dataclass(frozen=True, slots=True)
class ReadingGenerationClaim:
    status: ReadingGenerationClaimStatus
    context: ReadingGenerationContext | None = None
    ready: StoredReadingResult | None = None

    def __post_init__(self) -> None:
        if self.status is ReadingGenerationClaimStatus.CLAIMED:
            if self.context is None or self.ready is not None:
                raise ValueError("claimed generation requires context only")
        elif self.status is ReadingGenerationClaimStatus.READY:
            if self.ready is None or self.context is not None:
                raise ValueError("ready generation requires stored result only")
        elif self.context is not None or self.ready is not None:
            raise ValueError("terminal generation claim cannot carry content")


@dataclass(frozen=True, slots=True)
class ReadingSymbolContext:
    symbol: ReadingSymbolInput
    display_name: str
    interpretation_theme: str

    def __post_init__(self) -> None:
        if not self.display_name.strip() or len(self.display_name) > 200:
            raise ValueError("invalid symbol display name")
        if not self.interpretation_theme.strip() or len(self.interpretation_theme) > 2000:
            raise ValueError("invalid symbol interpretation theme")
