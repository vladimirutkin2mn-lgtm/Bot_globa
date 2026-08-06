"""Content-free lifecycle contracts for oracle memory retention and usefulness."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MemoryLifecycleEventType(StrEnum):
    CREATED = "created"
    EXTRACTED = "extracted"
    USED = "used"
    DELETED = "deleted"
    CORRECTED = "corrected"
    DEDUPLICATED = "deduplicated"
    SUPERSEDED = "superseded"
    DECAYED = "decayed"
    CAPACITY_RETIRED = "capacity_retired"


@dataclass(frozen=True, slots=True)
class MemoryUsefulnessSummary:
    created_count: int
    extracted_count: int
    used_count: int
    deleted_count: int
    corrected_count: int
    deduplicated_count: int
    superseded_count: int
    decayed_count: int
    capacity_retired_count: int
    observed_at: datetime

    def __post_init__(self) -> None:
        counts = (
            self.created_count,
            self.extracted_count,
            self.used_count,
            self.deleted_count,
            self.corrected_count,
            self.deduplicated_count,
            self.superseded_count,
            self.decayed_count,
            self.capacity_retired_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("memory usefulness counts cannot be negative")
