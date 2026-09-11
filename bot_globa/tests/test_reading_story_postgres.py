"""PostgreSQL invariants for encrypted user-managed reading stories."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.db.reading_story_models import ReadingStoryLink, ReadingStoryPrivateContent
from app.services.reading_story import (
    ReadingStoryNotFoundError,
    ReadingStoryReadingError,
    ReadingStoryService,
    ReadingStoryTitleError,
)
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Story")
        session.add(user)
        await session.flush()
        return user


async def _persona(sessions: async_sessionmaker[AsyncSession], code: str) -> Persona:
    async with sessions.begin() as session:
        persona = Persona(
            code=code,
            display_name="Story Persona",
            prompt_version="story-v1",
            schema_version="reading-result-v1",
        )
        session.add(persona)
        await session.flush()
        return persona


async def _reading(
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id,
    persona_id,
    ready: bool,
) -> Reading:
    async with sessions.begin() as session:
        reading = Reading(
            user_id=user_id,
            persona_id=persona_id,
            topic="decision",
            status="preview_ready" if ready else "draft",
            access_level="preview" if ready else "none",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="story-v1",
            schema_version="reading-result-v1",
            generated_at=datetime.now(UTC) if ready else None,
        )
        session.add(reading)
        await session.flush()
        return reading


async def test_story_encrypts_title_and_stays_owner_scoped(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _user(payment_db, 940001)
    stranger = await _user(payment_db, 940002)
    service = ReadingStoryService(
        payment_db,
        AESGCMSensitiveContentCipher("reading-story-postgres-key"),
    )
    secret = "Отношения с человеком из прошлого"

    created = await service.create(owner.id, f"  {secret}  ")
    assert created.title == secret
    assert created.reading_ids == ()

    async with payment_db() as session:
        private = await session.get(ReadingStoryPrivateContent, created.id)
        assert private is not None
        assert secret.encode() not in private.title_ciphertext

    listed = await service.list_for_user(owner.id)
    assert [(story.id, story.title) for story in listed] == [(created.id, secret)]
    assert await service.list_for_user(stranger.id) == []
    with pytest.raises(ReadingStoryNotFoundError):
        await service.get(stranger.id, created.id)

    renamed = await service.rename(owner.id, created.id, "Новая глава")
    assert renamed.title == "Новая глава"
    with pytest.raises(ReadingStoryTitleError):
        await service.rename(owner.id, created.id, "   ")


async def test_story_links_only_owned_ready_readings_and_allows_manual_correction(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _user(payment_db, 940010)
    stranger = await _user(payment_db, 940011)
    persona = await _persona(payment_db, "story_links")
    ready = await _reading(
        payment_db,
        user_id=owner.id,
        persona_id=persona.id,
        ready=True,
    )
    draft = await _reading(
        payment_db,
        user_id=owner.id,
        persona_id=persona.id,
        ready=False,
    )
    foreign = await _reading(
        payment_db,
        user_id=stranger.id,
        persona_id=persona.id,
        ready=True,
    )
    service = ReadingStoryService(
        payment_db,
        AESGCMSensitiveContentCipher("reading-story-link-key"),
    )
    first = await service.create(owner.id, "Первая история")
    second = await service.create(owner.id, "Вторая история")

    await service.link_reading(owner.id, first.id, ready.id)
    assert (await service.get(owner.id, first.id)).reading_ids == (ready.id,)

    with pytest.raises(ReadingStoryReadingError):
        await service.link_reading(owner.id, first.id, draft.id)
    with pytest.raises(ReadingStoryReadingError):
        await service.link_reading(owner.id, first.id, foreign.id)

    await service.link_reading(owner.id, second.id, ready.id)
    assert (await service.get(owner.id, first.id)).reading_ids == ()
    assert (await service.get(owner.id, second.id)).reading_ids == (ready.id,)

    assert await service.unlink_reading(owner.id, second.id, ready.id) is True
    assert await service.unlink_reading(owner.id, second.id, ready.id) is False
    assert (await service.get(owner.id, second.id)).reading_ids == ()


async def test_deleting_story_keeps_reading_result(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _user(payment_db, 940020)
    persona = await _persona(payment_db, "story_delete")
    ready = await _reading(
        payment_db,
        user_id=owner.id,
        persona_id=persona.id,
        ready=True,
    )
    service = ReadingStoryService(
        payment_db,
        AESGCMSensitiveContentCipher("reading-story-delete-key"),
    )
    story = await service.create(owner.id, "Удаляемая история")
    await service.link_reading(owner.id, story.id, ready.id)

    await service.delete(owner.id, story.id)

    with pytest.raises(ReadingStoryNotFoundError):
        await service.get(owner.id, story.id)
    async with payment_db() as session:
        assert await session.get(Reading, ready.id) is not None
        assert await session.get(ReadingStoryLink, ready.id) is None
