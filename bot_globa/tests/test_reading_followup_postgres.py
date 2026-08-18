"""Real-PostgreSQL concurrency, release and grounding invariants for reading follow-ups."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import CreditTransaction, User
from app.db.reading_followups import ReadingFollowUp
from app.db.reading_models import Persona, Reading, ReadingPrivateContent
from app.providers.llm.base import LLMCompletion, LLMRequest, LLMTimeoutError
from app.services.reading_followup import ReadingFollowUpService, ReadingFollowUpStatus
from app.services.sensitive_content import AESGCMSensitiveContentCipher, ContentPurpose

pytestmark = pytest.mark.postgres

CIPHER_KEY = "reading-followup-test-key-material"


class AnalyticsRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str | None, str, Mapping[str, str] | None]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.events.append((user_id, event, properties))


def answer_payload(refs: list[str] | None = None) -> str:
    return json.dumps(
        {
            "answer": "Разбор уже описывает этот паттерн; опирайтесь на названный шаг.",
            "reading_refs": refs if refs is not None else ["title", "patterns.0"],
            "limitations": ["Ответ основан только на созданном разборе."],
            "safety": {"high_risk_detected": False, "categories": []},
        },
        ensure_ascii=False,
    )


class SlowLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        del request
        self.calls += 1
        await asyncio.sleep(0.2)
        return LLMCompletion(answer_payload(), "fake", "fake-model", "request-1", 10, 20, 30)


class SequenceLLM:
    def __init__(self, *outputs: str | Exception) -> None:
        self.outputs = list(outputs)
        self.calls = 0
        self.requests: list[LLMRequest] = []

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.calls += 1
        self.requests.append(request)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return LLMCompletion(output, "fake", "fake-model", f"request-{self.calls}", 1, 2, 3)


@pytest.fixture
async def followup_db() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def reading_result_payload() -> dict[str, object]:
    return {
        "title": "Взвешенный взгляд на выбор",
        "opening": "Расклад описывает направление, компромиссы и практическую паузу.",
        "symbols": [],
        "patterns": ["Срочность стоит отделить от важности."],
        "possible_scenarios": [
            {
                "scenario": "Короткая пауза делает компромиссы понятнее.",
                "conditions": ["Выпишите обратимые части каждого варианта."],
            }
        ],
        "reflection_questions": ["Какую ценность важнее сохранить?"],
        "practical_step": "Запишите один обратимый следующий шаг для каждого варианта.",
        "uncertainty_note": "Карты не определяют внешние события и не дают гарантий.",
        "share_card": {
            "headline": "Выбор просит осознанного направления",
            "short_text": "Отделите срочное от важного.",
        },
        "safety": {"high_risk_detected": False, "categories": []},
    }


async def paid_reading(
    sessions: async_sessionmaker[AsyncSession],
    *,
    access: str = "full",
    status: str = "full_ready",
) -> tuple[UUID, UUID]:
    cipher = AESGCMSensitiveContentCipher(CIPHER_KEY)
    async with sessions.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="ReadingFollowUp")
        persona = Persona(
            code=f"tarot_reader_{uuid4().hex[:6]}",
            display_name="Tarot Reader",
            prompt_version="tarot-reader-v2",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()
        reading = Reading(
            user_id=user.id,
            persona_id=persona.id,
            topic="decision",
            status="draft",
            access_level="none",
            cost_units=0,
            engine_version="tarot-symbolic-v1",
            prompt_version="tarot-reader-v2",
            schema_version="reading-result-v1",
        )
        session.add(reading)
        await session.flush()
        spend = CreditTransaction(
            user_id=user.id,
            type="spend",
            amount=-1,
            idempotency_key=f"reading_full_access:{reading.id}",
            reading_id=reading.id,
        )
        session.add(spend)
        await session.flush()
        session.add(
            ReadingPrivateContent(
                reading_id=reading.id,
                result_ciphertext=cipher.encrypt_json(
                    ContentPurpose.READING_RESULT,
                    reading_result_payload(),
                ),
            )
        )
        reading.status = status
        reading.generated_at = datetime.now(UTC)
        reading.access_level = access
        reading.cost_units = 1 if access == "full" else 0
        reading.full_access_transaction_id = spend.id if access == "full" else None
        return user.id, reading.id


def service(
    sessions: async_sessionmaker[AsyncSession],
    llm: SlowLLM | SequenceLLM,
) -> ReadingFollowUpService:
    return ReadingFollowUpService(
        sessions,
        AESGCMSensitiveContentCipher(CIPHER_KEY),
        llm,
        AnalyticsRecorder(),
        "fake",
        "fake-model",
        lease_seconds=2,
    )


async def test_concurrent_requests_make_one_llm_call_and_consume_once(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, reading_id = await paid_reading(followup_db)
    llm = SlowLLM()
    followups = service(followup_db, llm)

    outcomes = await asyncio.gather(
        followups.ask(reading_id, user_id, "Что здесь главное?"),
        followups.ask(reading_id, user_id, "Что здесь главное?"),
    )

    statuses = sorted(outcome.status.value for outcome in outcomes)
    assert statuses == ["completed", "processing"]
    assert llm.calls == 1
    async with followup_db() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(ReadingFollowUp)
            .where(ReadingFollowUp.reading_id == reading_id)
        )
        row = await session.scalar(
            select(ReadingFollowUp).where(ReadingFollowUp.reading_id == reading_id)
        )
    assert rows == 1
    assert row is not None
    assert row.status == "completed"
    assert row.claim_id is None


async def test_technical_failure_releases_entitlement_for_retry(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, reading_id = await paid_reading(followup_db)
    followups = service(followup_db, SequenceLLM(LLMTimeoutError("slow")))

    failed = await followups.ask(reading_id, user_id, "Что делать дальше?")

    assert failed.status is ReadingFollowUpStatus.FAILED_RELEASED
    assert failed.failure_code == "llm_timeout"
    async with followup_db() as session:
        row = await session.scalar(
            select(ReadingFollowUp).where(ReadingFollowUp.reading_id == reading_id)
        )
    assert row is not None
    assert row.status == "available"
    assert row.question_ciphertext is None
    assert row.answer_ciphertext is None

    retried = await service(followup_db, SequenceLLM(answer_payload())).ask(
        reading_id, user_id, "Что делать дальше?"
    )

    assert retried.status is ReadingFollowUpStatus.COMPLETED


async def test_soft_delete_purges_encrypted_followup_history(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, reading_id = await paid_reading(followup_db)
    completed = await service(followup_db, SequenceLLM(answer_payload())).ask(
        reading_id, user_id, "Что здесь главное?"
    )
    assert completed.status is ReadingFollowUpStatus.COMPLETED

    # Mirror the field resets the real deletion path performs, so the trigger sees a
    # genuine soft delete rather than a hand-crafted row.
    async with followup_db.begin() as session:
        reading = await session.get(Reading, reading_id)
        assert reading is not None
        reading.status = "deleted"
        reading.access_level = "none"
        reading.generation_started_at = None
        reading.generated_at = None
        reading.failure_code = None
        reading.deleted_at = datetime.now(UTC)

    async with followup_db() as session:
        remaining = await session.scalar(
            select(func.count())
            .select_from(ReadingFollowUp)
            .where(ReadingFollowUp.reading_id == reading_id)
        )
    assert remaining == 0


async def test_an_answer_citing_a_section_the_reading_lacks_is_refused(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    """symbols.0 does not exist in this reading, so the answer must not survive."""
    user_id, reading_id = await paid_reading(followup_db)
    llm = SequenceLLM(answer_payload(["symbols.0"]), answer_payload(["symbols.0"]))
    followups = service(followup_db, llm)

    outcome = await followups.ask(reading_id, user_id, "Что говорят карты?")

    assert outcome.status is ReadingFollowUpStatus.FAILED_RELEASED
    assert outcome.failure_code == "invalid_model_output"
    assert llm.calls == 2
    async with followup_db() as session:
        row = await session.scalar(
            select(ReadingFollowUp).where(ReadingFollowUp.reading_id == reading_id)
        )
    assert row is not None
    assert row.status == "available"
    assert row.answer_ciphertext is None


async def test_a_repair_attempt_recovers_a_wrongly_cited_answer(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, reading_id = await paid_reading(followup_db)
    llm = SequenceLLM(answer_payload(["reply_suggestions.0"]), answer_payload())
    followups = service(followup_db, llm)

    outcome = await followups.ask(reading_id, user_id, "Что здесь главное?")

    assert outcome.status is ReadingFollowUpStatus.COMPLETED
    assert llm.calls == 2
    assert llm.requests[1].repair
    assert "reading_refs" in llm.requests[1].user_prompt


async def test_a_preview_only_reading_has_no_followup_entitlement(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, reading_id = await paid_reading(followup_db, access="preview", status="preview_ready")
    llm = SequenceLLM(answer_payload())

    outcome = await service(followup_db, llm).ask(reading_id, user_id, "Что здесь главное?")

    assert outcome.status is ReadingFollowUpStatus.NOT_ELIGIBLE
    assert llm.calls == 0
    async with followup_db() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(ReadingFollowUp)
            .where(ReadingFollowUp.reading_id == reading_id)
        )
    assert rows == 0


async def test_session_allows_three_questions_and_stops_before_a_fourth_llm_call(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, reading_id = await paid_reading(followup_db)
    llm = SequenceLLM(answer_payload(), answer_payload(), answer_payload())
    followups = service(followup_db, llm)

    first = await followups.ask(reading_id, user_id, "Что здесь главное?")
    second = await followups.ask(reading_id, user_id, "А если иначе?")
    third = await followups.ask(reading_id, user_id, "Что ещё важно учесть?")
    fourth = await followups.ask(reading_id, user_id, "И ещё один вопрос?")

    assert first.status is ReadingFollowUpStatus.COMPLETED
    assert first.remaining_questions == 2
    assert second.status is ReadingFollowUpStatus.COMPLETED
    assert second.remaining_questions == 1
    assert second.view is not None
    assert second.view.question == "А если иначе?"
    assert third.status is ReadingFollowUpStatus.COMPLETED
    assert third.remaining_questions == 0
    assert third.view is not None
    assert third.view.question == "Что ещё важно учесть?"
    assert fourth.status is ReadingFollowUpStatus.COMPLETED
    assert fourth.remaining_questions == 0
    assert fourth.idempotent
    assert fourth.view is not None
    assert fourth.view.question == "Что ещё важно учесть?"
    assert llm.calls == 3
    async with followup_db() as session:
        row = await session.scalar(
            select(ReadingFollowUp).where(ReadingFollowUp.reading_id == reading_id)
        )
    assert row is not None
    assert row.reservation_count == 3


async def test_the_stored_question_and_answer_are_encrypted_at_rest(
    followup_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, reading_id = await paid_reading(followup_db)
    marker = "частный-вопрос-не-должен-утечь"

    await service(followup_db, SequenceLLM(answer_payload())).ask(reading_id, user_id, marker)

    async with followup_db() as session:
        row = await session.scalar(
            select(ReadingFollowUp).where(ReadingFollowUp.reading_id == reading_id)
        )
    assert row is not None
    assert row.question_ciphertext is not None
    assert marker.encode() not in row.question_ciphertext
    assert row.completed_at is not None
    assert row.completed_at <= datetime.now(UTC)
