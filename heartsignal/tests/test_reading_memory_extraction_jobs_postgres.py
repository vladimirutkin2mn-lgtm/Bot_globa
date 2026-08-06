"""PostgreSQL invariants for automatic completed-reading memory extraction jobs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import ReadingMemoryExtractionJob
from app.db.models import CreditTransaction, User
from app.db.reading_models import Persona
from app.domain.memory_extraction import (
    CompletedReadingMemorySnapshot,
    MemoryExtractionOutcome,
    MemoryExtractionPayload,
    MemoryExtractionStatus,
)
from app.domain.reading import (
    ReadingDraftRequest,
    ReadingSymbolInput,
    SymbolOrientation,
)
from app.repositories.readings import SqlAlchemyReadingRepository
from app.services.oracle_memory import OracleMemoryService
from app.services.reading_memory_extraction import ReadingMemoryExtractionService
from app.services.reading_memory_extraction_jobs import ReadingMemoryExtractionJobWorker
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


class EmptyReadingExtractor:
    version = "oracle-memory-extractor-v1"

    def __init__(self) -> None:
        self.calls = 0

    async def extract(
        self,
        snapshot: CompletedReadingMemorySnapshot,
    ) -> MemoryExtractionPayload:
        self.calls += 1
        assert snapshot.result["title"] == "Ready"
        return MemoryExtractionPayload(candidates=[])


class AlwaysFailingCompletedExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def extract_completed(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> MemoryExtractionOutcome:
        self.calls += 1
        raise RuntimeError("private provider detail must not be persisted")


async def _ready_reading(
    sessions: async_sessionmaker[AsyncSession],
    cipher: AESGCMSensitiveContentCipher,
    *,
    telegram_id: int,
) -> tuple[UUID, UUID]:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Job")
        persona = Persona(
            code=f"job_persona_{telegram_id}",
            display_name="Job Persona",
            prompt_version="persona-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()
        repository = SqlAlchemyReadingRepository(session, cipher)
        reading = await repository.create_draft(
            user.id,
            persona,
            ReadingDraftRequest(
                persona_code=persona.code,
                topic="life",
                question="What should I remember from this?",
                context="A durable context",
                engine_version="reading-v1",
                prompt_version="persona-v1",
                schema_version="reading-result-v1",
            ),
        )
        await repository.start_generation(reading.id, user.id)
        await repository.complete_generation(
            reading.id,
            user.id,
            {"title": "Ready"},
            [
                ReadingSymbolInput(
                    symbol_id="symbol-one",
                    position="focus",
                    orientation=SymbolOrientation.UPRIGHT,
                    catalog_version="catalog-v1",
                )
            ],
            full=False,
        )
        return user.id, reading.id


async def _job(
    sessions: async_sessionmaker[AsyncSession],
    reading_id: UUID,
) -> ReadingMemoryExtractionJob:
    async with sessions() as session:
        job = await session.scalar(
            select(ReadingMemoryExtractionJob).where(
                ReadingMemoryExtractionJob.reading_id == reading_id
            )
        )
        assert job is not None
        return job


async def test_ready_transition_enqueues_one_job_and_terminal_job_is_not_replayed(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("ora-303-completed-key")
    user_id, reading_id = await _ready_reading(
        payment_db,
        cipher,
        telegram_id=950001,
    )
    memory = OracleMemoryService(payment_db, cipher)
    await memory.grant_consent(user_id)
    extractor = EmptyReadingExtractor()
    extraction = ReadingMemoryExtractionService(payment_db, cipher, memory, extractor)
    worker = ReadingMemoryExtractionJobWorker(payment_db, extraction)

    assert await worker.run_once("worker-one") is True
    assert await worker.run_once("worker-one") is False
    assert extractor.calls == 1

    job = await _job(payment_db, reading_id)
    assert job.status == "completed"
    assert job.attempt_count == 1
    assert job.completed_at is not None
    assert job.last_error_code is None


async def test_no_consent_skips_before_extractor_and_full_transition_reactivates(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("ora-303-consent-key")
    user_id, reading_id = await _ready_reading(
        payment_db,
        cipher,
        telegram_id=950002,
    )
    memory = OracleMemoryService(payment_db, cipher)
    extractor = EmptyReadingExtractor()
    extraction = ReadingMemoryExtractionService(payment_db, cipher, memory, extractor)
    worker = ReadingMemoryExtractionJobWorker(payment_db, extraction)

    assert await worker.run_once("worker-consent") is True
    skipped = await _job(payment_db, reading_id)
    assert skipped.status == "skipped_no_consent"
    assert skipped.last_error_code == "memory_consent_required"
    assert extractor.calls == 0

    await memory.grant_consent(user_id)
    async with payment_db.begin() as session:
        spend = CreditTransaction(
            user_id=user_id,
            type="spend",
            amount=-1,
            idempotency_key=f"reading-full:{uuid4()}",
            reading_id=reading_id,
        )
        session.add(spend)
        await session.flush()
        repository = SqlAlchemyReadingRepository(session, cipher)
        await repository.promote_full_access(reading_id, user_id, 1, spend.id)

    reactivated = await _job(payment_db, reading_id)
    assert reactivated.status == "pending"
    assert reactivated.attempt_count == 0
    assert reactivated.completed_at is None

    assert await worker.run_once("worker-consent") is True
    assert extractor.calls == 1
    assert (await _job(payment_db, reading_id)).status == "completed"


async def test_retry_is_bounded_and_persists_only_safe_error_codes(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("ora-303-retry-key")
    _, reading_id = await _ready_reading(
        payment_db,
        cipher,
        telegram_id=950003,
    )
    extractor = AlwaysFailingCompletedExtractor()
    worker = ReadingMemoryExtractionJobWorker(
        payment_db,
        extractor,
        retry_base_seconds=1,
        max_attempts=2,
    )

    assert await worker.run_once("worker-retry") is True
    first = await _job(payment_db, reading_id)
    assert first.status == "pending"
    assert first.attempt_count == 1
    assert first.last_error_code == "unexpected_memory_extraction_error"

    async with payment_db.begin() as session:
        job = await session.scalar(
            select(ReadingMemoryExtractionJob)
            .where(ReadingMemoryExtractionJob.reading_id == reading_id)
            .with_for_update()
        )
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)

    assert await worker.run_once("worker-retry") is True
    failed = await _job(payment_db, reading_id)
    assert failed.status == "failed"
    assert failed.attempt_count == 2
    assert failed.last_error_code == "memory_extraction_retry_exhausted"
    assert failed.completed_at is not None
    assert extractor.calls == 2


async def test_expired_claim_is_reclaimed_with_a_new_claim_id(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("ora-303-lease-key")
    _, reading_id = await _ready_reading(
        payment_db,
        cipher,
        telegram_id=950004,
    )
    worker = ReadingMemoryExtractionJobWorker(
        payment_db,
        AlwaysFailingCompletedExtractor(),
        lease_seconds=60,
    )

    first = await worker.claim_one("worker-a")
    assert first is not None
    async with payment_db.begin() as session:
        job = await session.get(
            ReadingMemoryExtractionJob,
            first.job_id,
            with_for_update=True,
        )
        assert job is not None
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)

    second = await worker.claim_one("worker-b")
    assert second is not None
    assert second.job_id == first.job_id
    assert second.reading_id == reading_id
    assert second.claim_id != first.claim_id
    assert (await _job(payment_db, reading_id)).attempt_count == 2
