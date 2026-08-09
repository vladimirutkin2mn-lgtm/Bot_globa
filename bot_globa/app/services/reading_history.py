"""Query safe reading metadata without decrypting private content."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_models import Persona, Reading
from app.domain.reading import ReadingStatus
from app.domain.reading_history import ReadingHistoryItem, ReadingHistoryPage


class ReadingHistoryService:
    """List ready readings using operational metadata only."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_ready(
        self,
        user_id: UUID,
        persona_code: str,
        *,
        page: int = 0,
        page_size: int = 8,
    ) -> ReadingHistoryPage:
        if page < 0:
            raise ValueError("reading history page must be non-negative")
        if page_size < 1 or page_size > 20:
            raise ValueError("reading history page size is invalid")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        Reading.id,
                        Reading.topic,
                        Reading.status,
                        Reading.created_at,
                    )
                    .join(Persona, Persona.id == Reading.persona_id)
                    .where(
                        Reading.user_id == user_id,
                        Persona.code == persona_code,
                        Reading.status.in_(
                            (
                                ReadingStatus.PREVIEW_READY.value,
                                ReadingStatus.FULL_READY.value,
                            )
                        ),
                        Reading.deleted_at.is_(None),
                    )
                    .order_by(Reading.created_at.desc(), Reading.id.desc())
                    .offset(page * page_size)
                    .limit(page_size + 1)
                )
            ).all()
        has_next = len(rows) > page_size
        visible = rows[:page_size]
        return ReadingHistoryPage(
            items=tuple(
                ReadingHistoryItem(
                    reading_id=row.id,
                    topic=row.topic,
                    status=row.status,
                    created_at=row.created_at,
                )
                for row in visible
            ),
            page=page,
            page_size=page_size,
            has_next=has_next,
        )
