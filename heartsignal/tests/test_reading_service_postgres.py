"""PostgreSQL coverage for the independent encrypted Reading domain."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading, ReadingPrivateContent, ReadingSymbol
from app.domain.reading import (
    InvalidReadingTransition,
    ReadingDraftRequest,
    ReadingStatus,
    ReadingSymbolInput,
    SymbolOrientation,
)
from app.services.reading_service import PersonaUnavailableError, ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def _seed(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[User, User, Persona]:
    async with sessions.begin() as session:
        owner = User(telegram_user_id=880001, first_name="Owner")
        stranger = User(telegram_user_id=880002, first_name="Stranger")
        persona = Persona(
            code="tarot_reader",
            display_name="Таролог",
            prompt_version="tarot-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owner, stranger, persona))
        await session.flush()
        return owner, stranger, persona


def _request(*, persona_code: str = "tarot_reader") -> ReadingDraftRequest:
    return ReadingDraftRequest(
        persona_code=persona_code,
        topic="decision",
        question="Что мне сейчас важно увидеть?",
        context="Я выбираю между двумя рабочими предложениями.",
        engine_version="reading-v1",
        prompt_version="tarot-v1",
        schema_version="reading-result-v1",
        cost_units=1,
    )


def _symbols() -> list[ReadingSymbolInput]:
    return [
        ReadingSymbolInput(
            symbol_id="major_02",
            position="current_influence",
            orientation=SymbolOrientation.REVERSED,
            catalog_version="tarot-v1",
        ),
        ReadingSymbolInput(
            symbol_id="major_06",
            position="next_step",
            orientation=SymbolOrientation.UPRIGHT,
            catalog_version="tarot-v1",
        ),
    ]


async def test_reading_lifecycle_encrypts_content_and_purges_on_delete(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner, _, _ = await _seed(payment_db)
    cipher = AESGCMSensitiveContentCipher("reading-postgres-test-key-material")
    service = ReadingService(payment_db, cipher, retention_days=7)

    reading = await service.create_draft(owner.id, _request())
    assert reading.status == ReadingStatus.DRAFT.value
    assert await service.load_source(reading.id, owner.id) is not None

    async with payment_db() as session:
        private = await session.get(ReadingPrivateContent, reading.id)
        assert private is not None
        assert private.question_ciphertext is not None
        assert b"important" not in private.question_ciphertext
        assert "Что мне".encode() not in private.question_ciphertext
        assert private.context_ciphertext is not None
        assert "рабочими".encode() not in private.context_ciphertext

    await service.start_generation(reading.id, owner.id)
    result = {"title": "Выбор", "practical_step": "Сравнить обратимость решений"}
    preview = await service.complete_preview(reading.id, owner.id, result, _symbols())
    assert preview.status == ReadingStatus.PREVIEW_READY.value
    assert preview.access_level == "preview"
    assert await service.load_result(reading.id, owner.id) == result

    full = await service.promote_full_access(reading.id, owner.id)
    assert full.status == ReadingStatus.FULL_READY.value
    assert full.access_level == "full"
    assert await service.load_result(reading.id, owner.id) == result

    deleted = await service.delete_owned(reading.id, owner.id)
    assert deleted.status == ReadingStatus.DELETED.value
    assert await service.load_source(reading.id, owner.id) is None
    assert await service.load_result(reading.id, owner.id) is None

    async with payment_db() as session:
        stored = await session.get(Reading, reading.id)
        private = await session.get(ReadingPrivateContent, reading.id)
        symbol_count = await session.scalar(
            select(func.count())
            .select_from(ReadingSymbol)
            .where(ReadingSymbol.reading_id == reading.id)
        )
        assert stored is not None and stored.deleted_at is not None
        assert private is not None and private.content_deleted_at is not None
        assert private.question_ciphertext is None
        assert private.context_ciphertext is None
        assert private.result_ciphertext is None
        assert symbol_count == 0


async def test_reading_ownership_and_persona_availability_are_enforced(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner, stranger, _ = await _seed(payment_db)
    cipher = AESGCMSensitiveContentCipher("reading-ownership-test-key-material")
    service = ReadingService(payment_db, cipher)
    reading = await service.create_draft(owner.id, _request())

    assert await service.load_source(reading.id, stranger.id) is None
    with pytest.raises(LookupError, match="owned reading not found"):
        await service.start_generation(reading.id, stranger.id)
    with pytest.raises(PersonaUnavailableError):
        await service.create_draft(owner.id, _request(persona_code="disabled_oracle"))

    async with payment_db.begin() as session:
        disabled = Persona(
            code="disabled_oracle",
            display_name="Disabled",
            prompt_version="disabled-v1",
            schema_version="reading-result-v1",
            enabled=False,
        )
        session.add(disabled)
    with pytest.raises(PersonaUnavailableError):
        await service.create_draft(owner.id, _request(persona_code="disabled_oracle"))


async def test_failed_generation_can_retry_but_ready_reading_cannot_restart(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner, _, _ = await _seed(payment_db)
    service = ReadingService(
        payment_db,
        AESGCMSensitiveContentCipher("reading-retry-test-key-material"),
    )
    reading = await service.create_draft(owner.id, _request())

    await service.start_generation(reading.id, owner.id)
    failed = await service.fail_generation(reading.id, owner.id, "provider_timeout")
    assert failed.status == ReadingStatus.FAILED.value
    assert failed.failure_code == "provider_timeout"

    await service.start_generation(reading.id, owner.id)
    ready = await service.complete_full(
        reading.id,
        owner.id,
        {"title": "Retry succeeded"},
        _symbols(),
    )
    assert ready.status == ReadingStatus.FULL_READY.value

    with pytest.raises(InvalidReadingTransition):
        await service.start_generation(reading.id, owner.id)


async def test_duplicate_symbol_positions_are_rejected_atomically(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner, _, _ = await _seed(payment_db)
    service = ReadingService(
        payment_db,
        AESGCMSensitiveContentCipher("reading-symbol-test-key-material"),
    )
    reading = await service.create_draft(owner.id, _request())
    await service.start_generation(reading.id, owner.id)
    duplicate = [
        ReadingSymbolInput(
            symbol_id="major_01",
            position="same_position",
            catalog_version="tarot-v1",
        ),
        ReadingSymbolInput(
            symbol_id="major_02",
            position="same_position",
            catalog_version="tarot-v1",
        ),
    ]

    with pytest.raises(ValueError, match="duplicate reading symbol position"):
        await service.complete_preview(reading.id, owner.id, {"title": "Invalid"}, duplicate)

    async with payment_db() as session:
        stored = await session.get(Reading, reading.id)
        private = await session.get(ReadingPrivateContent, reading.id)
        assert stored is not None and stored.status == ReadingStatus.GENERATING.value
        assert private is not None and private.result_ciphertext is None
