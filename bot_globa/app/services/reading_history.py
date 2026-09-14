"""Query safe reading metadata without decrypting private content."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_models import Persona, Reading
from app.domain.reading import ReadingStatus
from app.domain.reading_history import (
    ReadingHistoryChoice,
    ReadingHistoryChoicePage,
    ReadingHistoryItem,
    ReadingHistoryPage,
)

_READY_STATUSES = (
    ReadingStatus.PREVIEW_READY.value,
    ReadingStatus.FULL_READY.value,
)


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
        self._validate_page(page, page_size)
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
                        Reading.status.in_(_READY_STATUSES),
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

    async def list_ready_all(
        self,
        user_id: UUID,
        *,
        page: int = 0,
        page_size: int = 8,
    ) -> ReadingHistoryChoicePage:
        """List all owned ready readings for manual story assignment."""

        self._validate_page(page, page_size)
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        Reading.id,
                        Persona.code.label("persona_code"),
                        Reading.topic,
                        Reading.status,
                        Reading.created_at,
                    )
                    .join(Persona, Persona.id == Reading.persona_id)
                    .where(
                        Reading.user_id == user_id,
                        Reading.status.in_(_READY_STATUSES),
                        Reading.deleted_at.is_(None),
                    )
                    .order_by(Reading.created_at.desc(), Reading.id.desc())
                    .offset(page * page_size)
                    .limit(page_size + 1)
                )
            ).all()
        has_next = len(rows) > page_size
        return ReadingHistoryChoicePage(
            items=tuple(self._choice(row) for row in rows[:page_size]),
            page=page,
            page_size=page_size,
            has_next=has_next,
        )

    async def ready_metadata(
        self,
        user_id: UUID,
        reading_ids: Sequence[UUID],
    ) -> tuple[ReadingHistoryChoice, ...]:
        """Resolve story members using safe metadata, newest reading first."""

        requested = tuple(reading_ids)
        if not requested:
            return ()
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        Reading.id,
                        Persona.code.label("persona_code"),
                        Reading.topic,
                        Reading.status,
                        Reading.created_at,
                    )
                    .join(Persona, Persona.id == Reading.persona_id)
                    .where(
                        Reading.user_id == user_id,
                        Reading.id.in_(requested),
                        Reading.status.in_(_READY_STATUSES),
                        Reading.deleted_at.is_(None),
                    )
                )
            ).all()
        choices = tuple(self._choice(row) for row in rows)
        return self._newest_first(choices)

    async def owns_ready(self, user_id: UUID, reading_id: UUID) -> bool:
        """Authorize feedback on either a free preview or an unlocked full reading."""

        async with self._sessions() as session:
            return bool(
                await session.scalar(
                    select(
                        exists().where(
                            Reading.id == reading_id,
                            Reading.user_id == user_id,
                            Reading.status.in_(_READY_STATUSES),
                            Reading.deleted_at.is_(None),
                        )
                    )
                )
            )

    async def owns_full(self, user_id: UUID, reading_id: UUID) -> bool:
        """Authorize a result action using metadata only, without decrypting the reading."""

        async with self._sessions() as session:
            return bool(
                await session.scalar(
                    select(
                        exists().where(
                            Reading.id == reading_id,
                            Reading.user_id == user_id,
                            Reading.status == ReadingStatus.FULL_READY.value,
                            Reading.deleted_at.is_(None),
                        )
                    )
                )
            )

    @staticmethod
    def _newest_first(
        choices: Sequence[ReadingHistoryChoice],
    ) -> tuple[ReadingHistoryChoice, ...]:
        return tuple(
            sorted(
                choices,
                key=lambda item: (item.created_at, item.reading_id.int),
                reverse=True,
            )
        )

    @staticmethod
    def _validate_page(page: int, page_size: int) -> None:
        if page < 0:
            raise ValueError("reading history page must be non-negative")
        if page_size < 1 or page_size > 20:
            raise ValueError("reading history page size is invalid")

    @staticmethod
    def _choice(row: object) -> ReadingHistoryChoice:
        return ReadingHistoryChoice(
            reading_id=row.id,  # type: ignore[attr-defined]
            persona_code=row.persona_code,  # type: ignore[attr-defined]
            topic=row.topic,  # type: ignore[attr-defined]
            status=row.status,  # type: ignore[attr-defined]
            created_at=row.created_at,  # type: ignore[attr-defined]
        )
