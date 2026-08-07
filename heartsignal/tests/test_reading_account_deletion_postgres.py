"""PostgreSQL privacy invariants for Reading data during account deletion."""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading, ReadingPrivateContent, ReadingSymbol
from app.domain.reading import (
    ReadingAccess,
    ReadingDraftRequest,
    ReadingStatus,
    ReadingSymbolInput,
    SymbolOrientation,
)
from app.domain.reading_generation import ReadingGenerationClaimStatus
from app.providers.analytics import NoOpAnalyticsClient
from app.repositories.reading_generation import SqlAlchemyReadingGenerationStore
from app.repositories.readings import SqlAlchemyReadingRepository
from app.services.data_deletion import DataDeletionOutcome, DataDeletionService
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def _user_and_persona(
    sessions: async_sessionmaker[AsyncSession],
    telegram_id: int,
) -> tuple[User, Persona]:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Reading Privacy")
        persona = Persona(
            code=f"reading_privacy_{telegram_id}",
            display_name="Reading Privacy",
            prompt_version="privacy-reading-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()
        return user, persona


async def _preview_reading(
    sessions: async_sessionmaker[AsyncSession],
    cipher: AESGCMSensitiveContentCipher,
    user: User,
    persona: Persona,
) -> UUID:
    async with sessions.begin() as session:
        repository = SqlAlchemyReadingRepository(session, cipher)
        reading = await repository.create_draft(
            user.id,
            persona,
            ReadingDraftRequest(
                persona_code=persona.code,
                topic="decision",
                question="PRIVATE-READING-QUESTION",
                context="PRIVATE-READING-CONTEXT",
                engine_version="symbolic-v1",
                prompt_version=persona.prompt_version,
                schema_version=persona.schema_version,
                cost_units=0,
            ),
        )
        await repository.start_generation(reading.id, user.id)
        await repository.complete_generation(
            reading.id,
            user.id,
            {"title": "PRIVATE-READING-RESULT"},
            [
                ReadingSymbolInput(
                    symbol_id="major-00-fool",
                    position="situation",
                    orientation=SymbolOrientation.UPRIGHT,
                    catalog_version="tarot-rws-v1",
                )
            ],
            full=False,
        )
        return reading.id


async def _delete_account(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    *,
    after_lock: Callable[[], Awaitable[None]] | None = None,
) -> DataDeletionOutcome:
    async with sessions() as session:
        return await DataDeletionService(
            session,
            NoOpAnalyticsClient(),
            _after_user_lock_for_test=after_lock,
        ).delete_account(user_id)


async def test_account_tombstone_purges_all_reading_ciphertext_and_symbols(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, persona = await _user_and_persona(payment_db, 897101)
    cipher = AESGCMSensitiveContentCipher("reading-account-deletion-key")
    reading_id = await _preview_reading(payment_db, cipher, user, persona)

    assert await _delete_account(payment_db, user.id) is DataDeletionOutcome.DELETED

    async with payment_db() as session:
        stored_user = await session.get(User, user.id)
        reading = await session.get(Reading, reading_id)
        private = await session.get(ReadingPrivateContent, reading_id)
        symbol_count = await session.scalar(
            select(func.count())
            .select_from(ReadingSymbol)
            .where(ReadingSymbol.reading_id == reading_id)
        )
    assert stored_user is not None and stored_user.privacy_status == "deleted"
    assert reading is not None
    assert reading.status == ReadingStatus.DELETED.value
    assert reading.access_level == ReadingAccess.NONE.value
    assert reading.generation_started_at is None
    assert reading.generated_at is None
    assert reading.failure_code is None
    assert reading.deleted_at is not None
    assert private is not None
    assert private.question_ciphertext is None
    assert private.context_ciphertext is None
    assert private.result_ciphertext is None
    assert private.question_format_version is None
    assert private.context_format_version is None
    assert private.result_format_version is None
    assert private.content_delete_after is None
    assert private.content_deleted_at is not None
    assert symbol_count == 0
    assert await ReadingService(payment_db, cipher).load_result(reading_id, user.id) is None
    assert await _delete_account(payment_db, user.id) is DataDeletionOutcome.ALREADY_DELETED


async def test_draft_creation_waits_for_deletion_and_cannot_leave_private_data(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, _ = await _user_and_persona(payment_db, 897102)
    cipher = AESGCMSensitiveContentCipher("reading-create-delete-race-key")
    locked = asyncio.Event()
    release = asyncio.Event()

    async def after_lock() -> None:
        locked.set()
        await release.wait()

    deletion = asyncio.create_task(_delete_account(payment_db, user.id, after_lock=after_lock))
    await locked.wait()
    creation = asyncio.create_task(
        ReadingService(payment_db, cipher).create_draft(
            user.id,
            ReadingDraftRequest(
                persona_code="reading_privacy_897102",
                topic="decision",
                question="PRIVATE-RACE-QUESTION",
                context=None,
                engine_version="symbolic-v1",
                prompt_version="privacy-reading-v1",
                schema_version="reading-result-v1",
                cost_units=0,
            ),
        )
    )
    await asyncio.sleep(0.05)
    assert not creation.done()
    release.set()

    assert await deletion is DataDeletionOutcome.DELETED
    with pytest.raises(LookupError, match="active reading user not found"):
        await creation
    async with payment_db() as session:
        count = await session.scalar(
            select(func.count()).select_from(Reading).where(Reading.user_id == user.id)
        )
    assert count == 0


async def test_generation_claim_waits_for_deletion_and_never_decrypts_source(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, persona = await _user_and_persona(payment_db, 897103)
    cipher = AESGCMSensitiveContentCipher("reading-claim-delete-race-key")
    async with payment_db.begin() as session:
        reading = await SqlAlchemyReadingRepository(session, cipher).create_draft(
            user.id,
            persona,
            ReadingDraftRequest(
                persona_code=persona.code,
                topic="decision",
                question="PRIVATE-CLAIM-QUESTION",
                context="PRIVATE-CLAIM-CONTEXT",
                engine_version="symbolic-v1",
                prompt_version=persona.prompt_version,
                schema_version=persona.schema_version,
                cost_units=0,
            ),
        )
        reading_id = reading.id

    locked = asyncio.Event()
    release = asyncio.Event()

    async def after_lock() -> None:
        locked.set()
        await release.wait()

    deletion = asyncio.create_task(_delete_account(payment_db, user.id, after_lock=after_lock))
    await locked.wait()
    claim_task = asyncio.create_task(
        SqlAlchemyReadingGenerationStore(payment_db, cipher).claim_preview(
            reading_id,
            user.id,
        )
    )
    await asyncio.sleep(0.05)
    assert not claim_task.done()
    release.set()

    assert await deletion is DataDeletionOutcome.DELETED
    claim = await claim_task
    assert claim.status is ReadingGenerationClaimStatus.NOT_FOUND
    assert claim.context is None
    async with payment_db() as session:
        reading = await session.get(Reading, reading_id)
        private = await session.get(ReadingPrivateContent, reading_id)
    assert reading is not None and reading.status == ReadingStatus.DELETED.value
    assert private is not None
    assert private.question_ciphertext is None
    assert private.context_ciphertext is None
    assert private.result_ciphertext is None
