"""PostgreSQL coverage for the one shared free preview entitlement."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Analysis, User
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
) -> tuple[User, Analysis, ReadingService, PreviewEntitlementService]:
    await PersonaRegistryService(payment_db).sync_mvp_personas()
    async with payment_db.begin() as session:
        user = User(telegram_user_id=930001, first_name="Shared Preview")
        session.add(user)
        await session.flush()
        analysis = Analysis(
  user_id=user.id,
  status="draft",
  intake_step="complete",
        )
        session.add(analysis)
        await session.flush()
    entitlements = PreviewEntitlementService(payment_db)
    readings = ReadingService(
        payment_db,
        AESGCMSensitiveContentCipher("shared-preview-entitlement-key-material"),
        preview_entitlements=entitlements,
    )
    return user, analysis, readings, entitlements


async def _draft(readings: ReadingService, user_id: object):
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


async def test_reading_preview_consumes_shared_entitlement_and_blocks_analysis(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, analysis, readings, entitlements = await _setup(payment_db)
    reading = await _draft(readings, user.id)

    assert (
        await entitlements.reserve_reading_preview(user.id, reading.id)
        is PreviewOutcome.RESERVED
    )
    await readings.start_generation(reading.id, user.id)
    await readings.complete_preview(reading.id, user.id, {"title": "Preview"}, [])
    assert (
        await entitlements.resolve_reading_visibility(user.id, reading.id)
        is ReadingPreviewVisibility.PREVIEW
    )
    assert await entitlements.reserve_preview(user.id, analysis.id) is PreviewOutcome.UNAVAILABLE

    state = await entitlements.get_preview_state(user.id)
    assert state is not None
    assert state.status == "consumed"
    assert state.analysis_id is None
    assert state.reading_id == reading.id


async def test_analysis_and_reading_reservations_are_mutually_exclusive(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, analysis, readings, entitlements = await _setup(payment_db)
    reading = await _draft(readings, user.id)

    outcomes = await asyncio.gather(
        entitlements.reserve_preview(user.id, analysis.id),
        entitlements.reserve_reading_preview(user.id, reading.id),
    )
    assert outcomes.count(PreviewOutcome.RESERVED) == 1
    assert outcomes.count(PreviewOutcome.UNAVAILABLE) == 1

    state = await entitlements.get_preview_state(user.id)
    assert state is not None and state.status == "reserved"
    assert (state.analysis_id is None) != (state.reading_id is None)


async def test_failed_reading_releases_and_retry_can_reserve(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, _, readings, entitlements = await _setup(payment_db)
    reading = await _draft(readings, user.id)
    assert (
        await entitlements.reserve_reading_preview(user.id, reading.id)
        is PreviewOutcome.RESERVED
    )
    await readings.start_generation(reading.id, user.id)
    await readings.fail_generation(reading.id, user.id, "provider_timeout")
    assert (
        await entitlements.resolve_reading_visibility(user.id, reading.id)
        is ReadingPreviewVisibility.LOCKED
    )
    state = await entitlements.get_preview_state(user.id)
    assert state is not None and state.status == "available"
    assert (
        await entitlements.reserve_reading_preview(user.id, reading.id)
        is PreviewOutcome.RESERVED
    )


async def test_second_ready_reading_is_locked_after_preview_consumed(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, _, readings, entitlements = await _setup(payment_db)
    first = await _draft(readings, user.id)
    assert (
        await entitlements.reserve_reading_preview(user.id, first.id)
        is PreviewOutcome.RESERVED
    )
    await readings.start_generation(first.id, user.id)
    await readings.complete_preview(first.id, user.id, {"title": "First"}, [])
    assert (
        await entitlements.resolve_reading_visibility(user.id, first.id)
        is ReadingPreviewVisibility.PREVIEW
    )

    second = await _draft(readings, user.id)
    assert (
        await entitlements.reserve_reading_preview(user.id, second.id)
        is PreviewOutcome.UNAVAILABLE
    )
    await readings.start_generation(second.id, user.id)
    await readings.complete_preview(second.id, user.id, {"title": "Second"}, [])
    assert (
        await entitlements.resolve_reading_visibility(user.id, second.id)
        is ReadingPreviewVisibility.LOCKED
    )


async def test_deleting_reserved_reading_releases_entitlement(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, _, readings, entitlements = await _setup(payment_db)
    reading = await _draft(readings, user.id)
    assert (
        await entitlements.reserve_reading_preview(user.id, reading.id)
        is PreviewOutcome.RESERVED
    )
    await readings.delete_owned(reading.id, user.id)
    state = await entitlements.get_preview_state(user.id)
    assert state is not None
    assert state.status == "available"
    assert state.analysis_id is None and state.reading_id is None
