"""PostgreSQL coverage for completed-reading memory extraction."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading, ReadingPrivateContent
from app.domain.memory_extraction import (
    CompletedReadingMemorySnapshot,
    MemoryExtractionCandidate,
    MemoryExtractionPayload,
    MemoryExtractionStatus,
)
from app.domain.oracle_memory import MemoryClaimBasis, MemoryKind
from app.services.oracle_memory import MemoryConsentRequiredError, OracleMemoryService
from app.services.reading_memory_extraction import ReadingMemoryExtractionService
from app.services.sensitive_content import AESGCMSensitiveContentCipher, ContentPurpose

pytestmark = pytest.mark.postgres


class StaticExtractor:
    version = "oracle-memory-extractor-v1"

    def __init__(self, payload: MemoryExtractionPayload) -> None:
        self.payload = payload
        self.calls = 0

    async def extract(
        self,
        snapshot: CompletedReadingMemorySnapshot,
    ) -> MemoryExtractionPayload:
        self.calls += 1
        assert snapshot.result["title"] == "Completed"
        return self.payload


class RevokeDuringExtraction:
    version = "oracle-memory-extractor-v1"

    def __init__(self, memory: OracleMemoryService, user_id: UUID) -> None:
        self._memory = memory
        self._user_id = user_id

    async def extract(
        self,
        snapshot: CompletedReadingMemorySnapshot,
    ) -> MemoryExtractionPayload:
        await self._memory.revoke_consent(self._user_id)
        return MemoryExtractionPayload(
            candidates=[
                MemoryExtractionCandidate(
                    kind=MemoryKind.USER_STATEMENT,
                    value="This must not be persisted after revocation",
                    confidence_milli=1000,
                    claim_basis=MemoryClaimBasis.USER_STATED,
                )
            ]
        )


async def _completed_reading(
    sessions: async_sessionmaker[AsyncSession],
    cipher: AESGCMSensitiveContentCipher,
    *,
    telegram_id: int,
    persona_code: str,
) -> tuple[User, Reading]:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Extractor")
        persona = Persona(
            code=persona_code,
            display_name="Extractor Persona",
            prompt_version="persona-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()
        reading = Reading(
            user_id=user.id,
            persona_id=persona.id,
            topic="life",
            status="preview_ready",
            access_level="preview",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="persona-v1",
            schema_version="reading-result-v1",
            generated_at=datetime.now(UTC),
        )
        session.add(reading)
        await session.flush()
        session.add(
            ReadingPrivateContent(
                reading_id=reading.id,
                question_ciphertext=cipher.encrypt_json(
                    ContentPurpose.READING_QUESTION,
                    "How should I reflect on what is happening?",
                ),
                context_ciphertext=cipher.encrypt_json(
                    ContentPurpose.READING_CONTEXT,
                    "I have a medical history, a legal dispute, debt, and crisis thoughts.",
                ),
                result_ciphertext=cipher.encrypt_json(
                    ContentPurpose.READING_RESULT,
                    {"title": "Completed"},
                ),
                question_format_version=1,
                context_format_version=1,
                result_format_version=1,
                content_deleted_at=None,
            )
        )
        await session.flush()
        return user, reading


def _topic_neutral_payload() -> MemoryExtractionPayload:
    return MemoryExtractionPayload(
        candidates=[
            MemoryExtractionCandidate(
                kind=MemoryKind.USER_STATEMENT,
                value="User reported a medical history",
                confidence_milli=1000,
                claim_basis=MemoryClaimBasis.USER_STATED,
            ),
            MemoryExtractionCandidate(
                kind=MemoryKind.USER_STATEMENT,
                value="User is involved in a legal dispute",
                confidence_milli=1000,
                claim_basis=MemoryClaimBasis.USER_STATED,
            ),
            MemoryExtractionCandidate(
                kind=MemoryKind.PERSONAL_GOAL,
                value="User wants to get out of debt",
                confidence_milli=950,
                claim_basis=MemoryClaimBasis.USER_STATED,
            ),
            MemoryExtractionCandidate(
                kind=MemoryKind.USER_STATEMENT,
                value="User reported crisis thoughts",
                confidence_milli=1000,
                claim_basis=MemoryClaimBasis.USER_STATED,
            ),
            MemoryExtractionCandidate(
                kind=MemoryKind.RECURRING_THEME,
                value="The reading inferred a recurring theme of control",
                confidence_milli=650,
                claim_basis=MemoryClaimBasis.MODEL_INFERRED,
            ),
        ]
    )


async def test_extraction_requires_consent_preserves_topics_and_is_idempotent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("ora-302-postgres-key")
    user, reading = await _completed_reading(
        payment_db,
        cipher,
        telegram_id=940001,
        persona_code="ora302_tarot",
    )
    memory = OracleMemoryService(payment_db, cipher)
    extractor = StaticExtractor(_topic_neutral_payload())
    service = ReadingMemoryExtractionService(payment_db, cipher, memory, extractor)

    with pytest.raises(MemoryConsentRequiredError):
        await service.extract_completed(reading.id, user.id)
    assert extractor.calls == 0

    await memory.grant_consent(user.id)
    first = await service.extract_completed(reading.id, user.id)
    repeated = await service.extract_completed(reading.id, user.id)

    assert first.status is MemoryExtractionStatus.COMPLETED
    assert first.created_count == 5
    assert first.skipped_count == 0
    assert repeated.created_count == 0
    assert repeated.skipped_count == 5

    active = await memory.list_active(user.id)
    assert len(active) == 5
    assert {item.value for item in active} == {
        "User reported a medical history",
        "User is involved in a legal dispute",
        "User wants to get out of debt",
        "User reported crisis thoughts",
        "The reading inferred a recurring theme of control",
    }
    inferred = [item for item in active if item.claim_basis is MemoryClaimBasis.MODEL_INFERRED]
    assert len(inferred) == 1


async def test_consent_is_rechecked_after_external_extraction(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("ora-302-revoke-race-key")
    user, reading = await _completed_reading(
        payment_db,
        cipher,
        telegram_id=940002,
        persona_code="ora302_race",
    )
    memory = OracleMemoryService(payment_db, cipher)
    await memory.grant_consent(user.id)
    service = ReadingMemoryExtractionService(
        payment_db,
        cipher,
        memory,
        RevokeDuringExtraction(memory, user.id),
    )

    with pytest.raises(MemoryConsentRequiredError):
        await service.extract_completed(reading.id, user.id)

    assert await memory.list_active(user.id) == []
