"""PostgreSQL coverage for the one-time off-question preview rescue."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Reading
from app.domain.reading import ReadingDraftRequest
from app.services.persona_registry import PersonaRegistryService
from app.services.preview_entitlement import (
    PreviewEntitlementService,
    PreviewOutcome,
    ReadingPreviewVisibility,
)
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def _setup(
    payment_db: async_sessionmaker[AsyncSession],
) -> tuple[User, ReadingService, PreviewEntitlementService]:
    await PersonaRegistryService(payment_db).sync_mvp_personas()
    async with payment_db.begin() as session:
        user = User(telegram_user_id=930101, first_name="Preview Rescue")
        session.add(user)
        await session.flush()
    entitlements = PreviewEntitlementService(payment_db)
    readings = ReadingService(
        payment_db,
        AESGCMSensitiveContentCipher("free-preview-rescue-key-material"),
        preview_entitlements=entitlements,
    )
    return user, readings, entitlements


async def _draft(readings: ReadingService, user_id: UUID) -> Reading:
    return await readings.create_draft(
        user_id,
        ReadingDraftRequest(
            persona_code="tarot_reader",
            topic="decision",
            question="What deserves attention?",
            engine_version="tarot-symbolic-v1",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
        ),
    )


async def _consume_first_preview(
    readings: ReadingService,
    entitlements: PreviewEntitlementService,
    user_id: UUID,
) -> Reading:
    reading = await _draft(readings, user_id)
    assert (
        await entitlements.reserve_reading_preview(user_id, reading.id) is PreviewOutcome.RESERVED
    )
    await readings.start_generation(reading.id, user_id)
    await readings.complete_preview(reading.id, user_id, {"title": "Preview"}, [])
    assert (
        await entitlements.resolve_reading_visibility(user_id, reading.id)
        is ReadingPreviewVisibility.PREVIEW
    )
    return reading


async def test_off_question_feedback_restores_exactly_one_full_preview(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, readings, entitlements = await _setup(payment_db)
    reading = await _consume_first_preview(readings, entitlements, user.id)

    assert await readings.restore_reading_preview_after_off_question_once(user.id, reading.id)

    state = await entitlements.get_preview_state(user.id)
    assert state is not None
    assert state.status == "available"
    assert state.analysis_id is None
    assert state.reading_id is None

    assert not await readings.restore_reading_preview_after_off_question_once(user.id, reading.id)

    replacement = await _draft(readings, user.id)
    assert (
        await entitlements.reserve_reading_preview(user.id, replacement.id)
        is PreviewOutcome.RESERVED
    )


async def test_concurrent_rescue_clicks_can_only_restore_once(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, readings, entitlements = await _setup(payment_db)
    reading = await _consume_first_preview(readings, entitlements, user.id)

    outcomes = await asyncio.gather(
        readings.restore_reading_preview_after_off_question_once(user.id, reading.id),
        readings.restore_reading_preview_after_off_question_once(user.id, reading.id),
    )

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1
