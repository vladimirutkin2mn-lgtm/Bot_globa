"""User-controlled grouping of completed readings into encrypted personal stories."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.reading_models import Reading
from app.db.reading_story_models import (
    ReadingStory,
    ReadingStoryLink,
    ReadingStoryPrivateContent,
)
from app.domain.reading import ReadingStatus
from app.domain.reading_story import ReadingStoryView
from app.services.sensitive_content import ContentPurpose, SensitiveContentCipher

_TITLE_MAX_LENGTH = 120
_TITLE_FORMAT_VERSION = 1
_READY_STATUSES = frozenset({ReadingStatus.PREVIEW_READY.value, ReadingStatus.FULL_READY.value})


class ReadingStoryError(ValueError):
    """Safe base error that never echoes private story content."""


class ReadingStoryNotFoundError(ReadingStoryError):
    def __init__(self) -> None:
        super().__init__("reading story not found")


class ReadingStoryReadingError(ReadingStoryError):
    def __init__(self) -> None:
        super().__init__("reading cannot be linked to story")


class ReadingStoryTitleError(ReadingStoryError):
    def __init__(self) -> None:
        super().__init__("invalid reading story title")


class ReadingStoryContentError(ReadingStoryError):
    def __init__(self) -> None:
        super().__init__("reading story content is unavailable")


class ReadingStoryService:
    """Persist manual story membership without copying reading private content."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: SensitiveContentCipher,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher

    async def create(self, user_id: UUID, title: str) -> ReadingStoryView:
        normalized = self._normalize_title(title)
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            story = ReadingStory(user_id=user_id, updated_at=now, links=[])
            story.private_content = ReadingStoryPrivateContent(
                title_ciphertext=self._cipher.encrypt_json(
                    ContentPurpose.READING_STORY_TITLE,
                    {"title": normalized},
                ),
                title_format_version=_TITLE_FORMAT_VERSION,
            )
            session.add(story)
            await session.flush()
            return self._view(story)

    async def list_for_user(self, user_id: UUID) -> list[ReadingStoryView]:
        async with self._sessions() as session:
            stories = list(
                await session.scalars(
                    select(ReadingStory)
                    .options(
                        selectinload(ReadingStory.private_content),
                        selectinload(ReadingStory.links),
                    )
                    .where(ReadingStory.user_id == user_id)
                    .order_by(ReadingStory.updated_at.desc(), ReadingStory.id)
                )
            )
            return [self._view(story) for story in stories]

    async def get(self, user_id: UUID, story_id: UUID) -> ReadingStoryView:
        async with self._sessions() as session:
            story = await session.scalar(self._owned_story_query(user_id, story_id))
            if story is None:
                raise ReadingStoryNotFoundError
            return self._view(story)

    async def rename(self, user_id: UUID, story_id: UUID, title: str) -> ReadingStoryView:
        normalized = self._normalize_title(title)
        async with self._sessions.begin() as session:
            story = await session.scalar(
                self._owned_story_query(user_id, story_id).with_for_update()
            )
            if story is None:
                raise ReadingStoryNotFoundError
            story.private_content.title_ciphertext = self._cipher.encrypt_json(
                ContentPurpose.READING_STORY_TITLE,
                {"title": normalized},
            )
            story.private_content.title_format_version = _TITLE_FORMAT_VERSION
            story.updated_at = datetime.now(UTC)
            await session.flush()
            return self._view(story)

    async def link_reading(self, user_id: UUID, story_id: UUID, reading_id: UUID) -> None:
        """Assign one ready owned reading, moving it from another story if necessary."""

        async with self._sessions.begin() as session:
            story = await session.scalar(
                select(ReadingStory)
                .where(ReadingStory.id == story_id, ReadingStory.user_id == user_id)
                .with_for_update()
            )
            if story is None:
                raise ReadingStoryNotFoundError
            reading = await session.scalar(
                select(Reading)
                .where(
                    Reading.id == reading_id,
                    Reading.user_id == user_id,
                    Reading.status.in_(_READY_STATUSES),
                    Reading.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if reading is None:
                raise ReadingStoryReadingError

            linked_at = datetime.now(UTC)
            link = await session.get(ReadingStoryLink, reading_id, with_for_update=True)
            if link is None:
                session.add(
                    ReadingStoryLink(
                        reading_id=reading_id,
                        story_id=story_id,
                        linked_at=linked_at,
                    )
                )
            else:
                link.story_id = story_id
                link.linked_at = linked_at
            story.updated_at = linked_at

    async def unlink_reading(self, user_id: UUID, story_id: UUID, reading_id: UUID) -> bool:
        async with self._sessions.begin() as session:
            story = await session.scalar(
                select(ReadingStory)
                .where(ReadingStory.id == story_id, ReadingStory.user_id == user_id)
                .with_for_update()
            )
            if story is None:
                raise ReadingStoryNotFoundError
            link = await session.get(ReadingStoryLink, reading_id, with_for_update=True)
            if link is None or link.story_id != story_id:
                return False
            await session.delete(link)
            story.updated_at = datetime.now(UTC)
            return True

    async def delete(self, user_id: UUID, story_id: UUID) -> None:
        async with self._sessions.begin() as session:
            story = await session.scalar(
                select(ReadingStory)
                .where(ReadingStory.id == story_id, ReadingStory.user_id == user_id)
                .with_for_update()
            )
            if story is None:
                raise ReadingStoryNotFoundError
            await session.delete(story)

    def _owned_story_query(self, user_id: UUID, story_id: UUID):  # type: ignore[no-untyped-def]
        return (
            select(ReadingStory)
            .options(
                selectinload(ReadingStory.private_content),
                selectinload(ReadingStory.links),
            )
            .where(ReadingStory.id == story_id, ReadingStory.user_id == user_id)
        )

    def _view(self, story: ReadingStory) -> ReadingStoryView:
        payload = self._cipher.decrypt_json(
            ContentPurpose.READING_STORY_TITLE,
            story.private_content.title_ciphertext,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("title"), str):
            raise ReadingStoryContentError
        title = payload["title"]
        if not title:
            raise ReadingStoryContentError
        return ReadingStoryView(
            id=story.id,
            title=title,
            reading_ids=tuple(link.reading_id for link in story.links),
            created_at=story.created_at,
            updated_at=story.updated_at,
        )

    @staticmethod
    def _normalize_title(title: str) -> str:
        if not isinstance(title, str):
            raise ReadingStoryTitleError
        normalized = " ".join(title.split())
        if not normalized or len(normalized) > _TITLE_MAX_LENGTH:
            raise ReadingStoryTitleError
        return normalized
