"""Transactional enqueue boundary for completed-reading memory extraction."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.memory_models import ReadingMemoryExtractionJob
from app.domain.memory_extraction import CURRENT_MEMORY_EXTRACTION_VERSION


async def enqueue_reading_memory_extraction(
    session: AsyncSession,
    reading_id: UUID,
    user_id: UUID,
    *,
    extraction_version: str = CURRENT_MEMORY_EXTRACTION_VERSION,
    reactivate_no_consent: bool = False,
) -> None:
    """Insert one versioned trigger, optionally reopening a prior no-consent skip."""

    now = datetime.now(UTC)
    statement = insert(ReadingMemoryExtractionJob).values(
        id=uuid4(),
        reading_id=reading_id,
        user_id=user_id,
        extraction_version=extraction_version,
        status="pending",
        attempt_count=0,
        available_at=now,
    )
    conflict_columns = (
        ReadingMemoryExtractionJob.reading_id,
        ReadingMemoryExtractionJob.extraction_version,
    )
    if reactivate_no_consent:
        statement = statement.on_conflict_do_update(
            index_elements=conflict_columns,
            set_={
                "status": "pending",
                "attempt_count": 0,
                "available_at": now,
                "claim_id": None,
                "claimed_by": None,
                "claimed_at": None,
                "lease_until": None,
                "last_error_code": None,
                "completed_at": None,
            },
            where=ReadingMemoryExtractionJob.status == "skipped_no_consent",
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=conflict_columns)
    await session.execute(statement)
