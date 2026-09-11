"""Manual user-owned stories that group existing oracle readings."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReadingStoryView:
    """Decrypted user-facing story metadata plus linked reading identifiers."""

    id: UUID
    title: str
    reading_ids: tuple[UUID, ...]
    created_at: datetime
    updated_at: datetime
