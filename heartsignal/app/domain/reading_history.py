"""Safe metadata contracts for paginated reading history."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReadingHistoryItem:
    reading_id: UUID
    topic: str
    status: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.topic or len(self.topic) > 64:
            raise ValueError("invalid reading history topic")


@dataclass(frozen=True, slots=True)
class ReadingHistoryPage:
    items: tuple[ReadingHistoryItem, ...]
    page: int
    page_size: int
    has_next: bool

    def __post_init__(self) -> None:
        if self.page < 0:
            raise ValueError("reading history page must be non-negative")
        if self.page_size < 1 or self.page_size > 20:
            raise ValueError("reading history page size is invalid")
        if len(self.items) > self.page_size:
            raise ValueError("reading history page exceeds page size")
