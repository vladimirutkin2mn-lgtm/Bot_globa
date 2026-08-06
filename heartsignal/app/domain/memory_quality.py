"""Non-secret quality metrics for consented oracle memory."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MemoryQualitySummary:
    active_count: int
    user_stated_count: int
    model_inferred_count: int
    stale_count: int
    correction_count: int
    duplicate_group_count: int
    observed_at: datetime

    def __post_init__(self) -> None:
        counts = (
            self.active_count,
            self.user_stated_count,
            self.model_inferred_count,
            self.stale_count,
            self.correction_count,
            self.duplicate_group_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("memory quality counts cannot be negative")
        if self.user_stated_count + self.model_inferred_count != self.active_count:
            raise ValueError("memory quality epistemic counts must equal active count")
        if self.stale_count > self.active_count:
            raise ValueError("stale memory count cannot exceed active count")
        if self.correction_count > self.active_count:
            raise ValueError("correction count cannot exceed active count")
