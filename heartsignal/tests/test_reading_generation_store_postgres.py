"""PostgreSQL locking and state coverage for reading generation claims."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona
from app.domain.reading import ReadingDraftRequest, ReadingStatus, ReadingSymbolInput
from app.domain.reading_generation import (
    ReadingGenerationClaimStatus,
    ReadingGenerationFinalizeStatus,
)
from app.repositories.reading_generation import SqlAlchemyReadingGenerationStore
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


def _request() -> ReadingDraftRequest:
    return ReadingDraftRequest(
        persona_code="tarot_reader",
        topic="decision",
        question="Which trade-off needs a slower review?",
        context="Both options are reversible but have different learning value.",
        engine_version="symbolic-v1",
        prompt_version="tarot-reader-v1",
        schema_version="reading-result-v1",
        cost_units=0,
    )


def _symbols() -> tuple[ReadingSymbolInput, ...]:
    return (
        ReadingSymbolInput(
            symbol_id="major_20",
            position="current_influence",
            orientation="reversed",
            catalog_version="tarot-major-v1",
        ),
        ReadingSymbolInput(
            symbol_id="major_07",
            position="hidden_factor",
            orientation="upright",
            catalog_version="tarot-major-v1",
        ),
    )


async def _seed(
    sessions: async_sessionmaker[AsyncSession],
    *,
    telegram_offset: int,
) -> tuple[User, User, Persona]:
    async with sessions.begin() as session:
        owner = User(
            telegram_user_id=891000 + telegram_offset,
            first_name="GenerationOwner",
        )
        stranger = User(
            telegram_user_id=892000 + telegram_offset,
            first_name="GenerationStranger",
        )
        persona = Persona(
            code=f"tarot_reader_{telegram_offset}",
            display_name="Tarot Reader",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owner, stranger, persona))
        await session.flush()
        return owner, stranger, persona


async def _draft(
    sessions: async_sessionmaker[AsyncSession],
    cipher: AESGCMSensitiveContentCipher,
    *,
    telegram_offset: int,
) -> tuple[User, User, Persona, object]:
    owner, stranger, persona = await _seed(
        sessions,
        telegram_offset=telegram_offset,
    )
    request = _request().model_copy(update={"persona_code": persona.code})
    reading = await ReadingService(sessions, cipher).create_draft(owner.id, request)
    return owner, stranger, persona, reading


async def test_claim_is_exactly_once_and_contains_decrypted_source(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("generation-claim-postgres-key-material")
    owner, _, _, reading = await _draft(
        payment_db,
        cipher,
        telegram_offset=1,
    )
    store = SqlAlchemyReadingGenerationStore(payment_db, cipher)

    first = await store.claim_preview(reading.id, owner.id)
    second = await store.claim_preview(reading.id, owner.id)

    assert first.status is ReadingGenerationClaimStatus.CLAIMED
    assert first.context is not None
    assert first.context.question == "Which trade-off needs a slower review?"
    assert first.context.prompt_version == "tarot-reader-v1"
    assert second.status is ReadingGenerationClaimStatus.ALREADY_PROCESSING


async def test_complete_preview_replays_payload_and_symbols_without_new_claim(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("generation-ready-postgres-key-material")
    owner, _, _, reading = await _draft(
        payment_db,
        cipher,
        telegram_offset=2,
    )
    store = SqlAlchemyReadingGenerationStore(payment_db, cipher)

    claimed = await store.claim_preview(reading.id, owner.id)
    completed = await store.complete_preview(
        reading.id,
        owner.id,
        {"title": "Validated result", "schema": "reading-result-v1"},
        _symbols(),
    )
    replay = await store.claim_preview(reading.id, owner.id)

    assert claimed.status is ReadingGenerationClaimStatus.CLAIMED
    assert completed is ReadingGenerationFinalizeStatus.COMPLETED
    assert replay.status is ReadingGenerationClaimStatus.READY
    assert replay.ready is not None
    assert replay.ready.payload["title"] == "Validated result"
    assert replay.ready.symbols == _symbols()


async def test_failure_is_retryable_and_clears_previous_failure_code(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("generation-retry-postgres-key-material")
    owner, _, _, reading = await _draft(
        payment_db,
        cipher,
        telegram_offset=3,
    )
    store = SqlAlchemyReadingGenerationStore(payment_db, cipher)

    assert (
        await store.claim_preview(reading.id, owner.id)
    ).status is ReadingGenerationClaimStatus.CLAIMED
    failed = await store.fail_generation(reading.id, owner.id, "llm_timeout")
    retried = await store.claim_preview(reading.id, owner.id)

    assert failed is ReadingGenerationFinalizeStatus.COMPLETED
    assert retried.status is ReadingGenerationClaimStatus.CLAIMED
    async with payment_db() as session:
        stored = await session.get(type(reading), reading.id)
        assert stored is not None
        assert stored.status == ReadingStatus.GENERATING.value
        assert stored.failure_code is None


async def test_disabled_persona_and_non_owner_cannot_claim(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("generation-access-postgres-key-material")
    owner, stranger, persona, reading = await _draft(
        payment_db,
        cipher,
        telegram_offset=4,
    )
    store = SqlAlchemyReadingGenerationStore(payment_db, cipher)

    non_owner = await store.claim_preview(reading.id, stranger.id)
    async with payment_db.begin() as session:
        stored_persona = await session.get(Persona, persona.id)
        assert stored_persona is not None
        stored_persona.enabled = False
    disabled = await store.claim_preview(reading.id, owner.id)

    assert non_owner.status is ReadingGenerationClaimStatus.NOT_FOUND
    assert disabled.status is ReadingGenerationClaimStatus.PERSONA_DISABLED


async def test_delete_during_generation_prevents_late_result_persistence(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("generation-delete-postgres-key-material")
    owner, _, _, reading = await _draft(
        payment_db,
        cipher,
        telegram_offset=5,
    )
    store = SqlAlchemyReadingGenerationStore(payment_db, cipher)
    service = ReadingService(payment_db, cipher)

    claimed = await store.claim_preview(reading.id, owner.id)
    deleted = await service.delete_owned(reading.id, owner.id)
    late_complete = await store.complete_preview(
        reading.id,
        owner.id,
        {"title": "Must not persist"},
        _symbols(),
    )

    assert claimed.status is ReadingGenerationClaimStatus.CLAIMED
    assert deleted.status == ReadingStatus.DELETED.value
    assert late_complete is ReadingGenerationFinalizeStatus.DELETED
    assert await service.load_result(reading.id, owner.id) is None
