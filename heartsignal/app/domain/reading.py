"""Core types and state transitions for oracle readings."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PersonaCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=64, pattern=r"^[a-z0-9_]+$"),
]
TopicCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=64, pattern=r"^[a-z0-9_]+$"),
]
PrivateText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)
]
VersionCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"
    ),
]


class StrictReadingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReadingStatus(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    PREVIEW_READY = "preview_ready"
    FULL_READY = "full_ready"
    FAILED = "failed"
    DELETED = "deleted"


class ReadingAccess(StrEnum):
    NONE = "none"
    PREVIEW = "preview"
    FULL = "full"


class SymbolOrientation(StrEnum):
    UPRIGHT = "upright"
    REVERSED = "reversed"
    NEUTRAL = "neutral"


_ALLOWED_TRANSITIONS: dict[ReadingStatus, frozenset[ReadingStatus]] = {
    ReadingStatus.DRAFT: frozenset({ReadingStatus.GENERATING, ReadingStatus.DELETED}),
    ReadingStatus.GENERATING: frozenset(
        {
            ReadingStatus.PREVIEW_READY,
            ReadingStatus.FULL_READY,
            ReadingStatus.FAILED,
            ReadingStatus.DELETED,
        }
    ),
    ReadingStatus.PREVIEW_READY: frozenset(
        {ReadingStatus.FULL_READY, ReadingStatus.DELETED}
    ),
    ReadingStatus.FULL_READY: frozenset({ReadingStatus.DELETED}),
    ReadingStatus.FAILED: frozenset({ReadingStatus.GENERATING, ReadingStatus.DELETED}),
    ReadingStatus.DELETED: frozenset(),
}


class InvalidReadingTransition(ValueError):
    """Safe state-machine error that contains no private reading content."""


def ensure_reading_transition(current: ReadingStatus, target: ReadingStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidReadingTransition(f"invalid reading transition: {current} -> {target}")


class ReadingDraftRequest(StrictReadingModel):
    persona_code: PersonaCode
    topic: TopicCode
    question: PrivateText
    context: str | None = Field(default=None, max_length=12000)
    engine_version: VersionCode
    prompt_version: VersionCode
    schema_version: VersionCode
    cost_units: int = Field(default=0, ge=0)


class ReadingSymbolInput(StrictReadingModel):
    symbol_id: VersionCode
    position: VersionCode
    orientation: SymbolOrientation = SymbolOrientation.NEUTRAL
    catalog_version: VersionCode
