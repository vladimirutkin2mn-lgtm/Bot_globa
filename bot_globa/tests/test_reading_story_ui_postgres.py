"""PostgreSQL contracts used by the reading-story Telegram UI."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.services.reading_history import ReadingHistoryService
from app.services.reading_story import ReadingStoryService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def test_cross_persona_story_choices_use_only_owned_ready_metadata(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with payment_db.begin() as session:
        owner = User(telegram_user_id=941001, first_name="StoryUIOwner")
        stranger = User(telegram_user_id=941002, first_name="StoryUIStranger")
        tarot = Persona(
            code="tarot_reader",
            display_name="Tarot",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
        )
        love = Persona(
            code="love_oracle",
            display_name="Love",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owner, stranger, tarot, love))
        await session.flush()

        newest = Reading(
            user_id=owner.id,
            persona_id=love.id,
            topic="communication",
            status="preview_ready",
            access_level="preview",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
            generated_at=now,
            created_at=now,
        )
        older = Reading(
            user_id=owner.id,
            persona_id=tarot.id,
            topic="work",
            status="preview_ready",
            access_level="preview",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
            generated_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        )
        excluded_draft = Reading(
            user_id=owner.id,
            persona_id=tarot.id,
            topic="decision",
            status="draft",
            access_level="none",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
            created_at=now + timedelta(minutes=1),
        )
        excluded_foreign = Reading(
            user_id=stranger.id,
            persona_id=tarot.id,
            topic="decision",
            status="preview_ready",
            access_level="preview",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
            generated_at=now + timedelta(minutes=2),
            created_at=now + timedelta(minutes=2),
        )
        session.add_all((newest, older, excluded_draft, excluded_foreign))
        await session.flush()
        owner_id = owner.id
        newest_id, older_id = newest.id, older.id

    history = ReadingHistoryService(payment_db)
    page = await history.list_ready_all(owner_id)
    assert [(item.reading_id, item.persona_code) for item in page.items] == [
        (newest_id, "love_oracle"),
        (older_id, "tarot_reader"),
    ]

    ordered = await history.ready_metadata(owner_id, (older_id, newest_id))
    assert [item.reading_id for item in ordered] == [older_id, newest_id]


async def test_unlink_owned_reading_cannot_remove_another_users_story_link(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with payment_db.begin() as session:
        owner = User(telegram_user_id=941010, first_name="StoryOwner")
        stranger = User(telegram_user_id=941011, first_name="StoryStranger")
        persona = Persona(
            code="tarot_reader",
            display_name="Tarot",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owner, stranger, persona))
        await session.flush()
        reading = Reading(
            user_id=owner.id,
            persona_id=persona.id,
            topic="decision",
            status="preview_ready",
            access_level="preview",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="story-ui-v1",
            schema_version="reading-result-v1",
            generated_at=now,
            created_at=now,
        )
        session.add(reading)
        await session.flush()
        owner_id, stranger_id, reading_id = owner.id, stranger.id, reading.id

    stories = ReadingStoryService(
        payment_db,
        AESGCMSensitiveContentCipher("reading-story-ui-owner-key"),
    )
    story = await stories.create(owner_id, "Работа")
    await stories.link_reading(owner_id, story.id, reading_id)

    assert await stories.unlink_owned_reading(stranger_id, reading_id) is None
    assert (await stories.get(owner_id, story.id)).reading_ids == (reading_id,)

    assert await stories.unlink_owned_reading(owner_id, reading_id) == story.id
    assert (await stories.get(owner_id, story.id)).reading_ids == ()
