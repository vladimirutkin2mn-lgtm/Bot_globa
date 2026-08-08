"""Golden and adversarial coverage for the Love Oracle persona."""

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.domain.oracle_safety import OracleSafetyAction
from app.domain.reading import ReadingAccess, ReadingDraftRequest, ReadingStatus
from app.domain.reading_generation import ReadingSymbolContext
from app.prompts.reading import load_reading_prompts
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.repositories.reading_generation import SqlAlchemyReadingGenerationStore
from app.services.persona_reading import (
    PersonaPreviewRequest,
    PersonaReadingUseCase,
    UnsafePersonaInputError,
    UnsupportedPersonaTopicError,
)
from app.services.reading_generation import (
    ReadingGenerationResult,
    ReadingGenerationService,
    ReadingGenerationStatus,
)
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher


class CapturingDraftService:
    def __init__(self) -> None:
        self.reading_id = uuid4()
        self.requests: list[tuple[UUID, ReadingDraftRequest]] = []

    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading:
        self.requests.append((user_id, request))
        return Reading(id=self.reading_id)


class CapturingGenerationService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, tuple[ReadingSymbolContext, ...]]] = []

    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult:
        self.calls.append((reading_id, user_id, symbol_contexts))
        return ReadingGenerationResult(ReadingGenerationStatus.COMPLETED)


class GoldenLoveOracleLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        payload = {
            "title": "A grounded look at distance and communication",
            "opening": (
                "The current distance may be easier to understand through observable patterns "
                "and the choices available to you."
            ),
            "symbols": [],
            "patterns": [
                "Unclear expectations can make silence feel more definitive than it is.",
                "A direct boundary can reduce the need to guess another person's inner state.",
            ],
            "possible_scenarios": [
                {
                    "scenario": "A calm conversation clarifies whether communication is mutual.",
                    "conditions": [
                        "Choose a neutral moment.",
                        "Ask one direct question without demanding a particular answer.",
                    ],
                },
                {
                    "scenario": "Continued distance becomes information about availability.",
                    "conditions": [
                        "Respect an unanswered message and return attention to yourself."
                    ],
                },
            ],
            "reflection_questions": [
                "What response would meet your minimum standard for reciprocity?",
                "Which boundary would reduce repeated guessing?",
            ],
            "practical_step": (
                "Write one short, respectful message and decide in advance what boundary you will "
                "keep if there is no reply."
            ),
            "uncertainty_note": (
                "This reflection cannot know the other person's private feelings or predict what "
                "they will do."
            ),
            "share_card": {
                "headline": "Clarity begins with what you can observe",
                "short_text": "Choose direct communication and a boundary you can keep.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="structured-fake",
            model="love-oracle-golden",
        )


class MindReadingLoveOracleLLM:
    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        del request
        payload = {
            "title": "His hidden feelings",
            "opening": "He definitely loves you and is secretly planning to return next Friday.",
            "symbols": [],
            "patterns": [],
            "possible_scenarios": [
                {
                    "scenario": "He will contact you next Friday.",
                    "conditions": ["Wait for his message."],
                }
            ],
            "reflection_questions": [],
            "practical_step": "Keep waiting because his return is certain.",
            "uncertainty_note": "This outcome is guaranteed.",
            "share_card": {
                "headline": "He is coming back",
                "short_text": "His secret love guarantees reunion next Friday.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="adversarial-fake",
            model="love-oracle-mind-reading",
        )


def test_love_oracle_prompt_is_memory_aware_and_rejects_inner_state_claims() -> None:
    prompt = load_reading_prompts("love-oracle-v1")

    assert prompt.accepts_memory_context
    assert "private thoughts, feelings, intentions" in prompt.system
    assert "observable relationship dynamics" in prompt.system
    assert "selected_symbols must be empty" in prompt.request_instruction
    assert "do not answer by inventing the other person's inner state" in prompt.request_instruction


async def test_use_case_freezes_love_versions_and_passes_no_symbols() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("love_oracle", drafts, generation)
    user_id = uuid4()

    first = await use_case.create_preview(
        user_id,
        PersonaPreviewRequest(
            topic="communication",
            question="How can I ask for clarity without applying pressure?",
            context="We have spoken less often during the last two weeks.",
        ),
    )
    replay = await use_case.generate_existing_preview(first.reading_id, user_id)

    assert replay.reading_id == first.reading_id
    assert len(drafts.requests) == 1
    _, request = drafts.requests[0]
    assert request.persona_code == "love_oracle"
    assert request.engine_version == "symbolic-v1"
    assert request.prompt_version == "love-oracle-v1"
    assert request.schema_version == "reading-result-v1"
    assert request.cost_units == 0
    assert generation.calls == [
        (first.reading_id, user_id, ()),
        (first.reading_id, user_id, ()),
    ]


async def test_unsupported_topic_is_rejected_before_draft_creation() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("love_oracle", drafts, generation)

    with pytest.raises(
        UnsupportedPersonaTopicError,
        match="unsupported topic for persona love_oracle",
    ):
        await use_case.create_preview(
            uuid4(),
            PersonaPreviewRequest(
                topic="medical_diagnosis",
                question="What illness explains this relationship?",
            ),
        )

    assert not drafts.requests and not generation.calls


async def test_unsafe_input_stops_before_draft_and_generation() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("love_oracle", drafts, generation)

    with pytest.raises(UnsafePersonaInputError) as captured:
        await use_case.create_preview(
            uuid4(),
            PersonaPreviewRequest(
                topic="love",
                question="I want to kill myself if this person does not return.",
            ),
        )

    assert captured.value.action is OracleSafetyAction.HANDOFF
    assert not drafts.requests and not generation.calls


@pytest.mark.postgres
async def test_postgres_love_oracle_preview_is_validated_and_idempotent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("love-oracle-vertical-key-material")
    async with payment_db.begin() as session:
        user = User(telegram_user_id=894001, first_name="LoveOracleGolden")
        persona = Persona(
            code="love_oracle",
            display_name="Love Oracle",
            prompt_version="love-oracle-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()

    readings = ReadingService(payment_db, cipher)
    llm = GoldenLoveOracleLLM()
    generation = ReadingGenerationService(
        SqlAlchemyReadingGenerationStore(payment_db, cipher),
        llm,
    )
    use_case = PersonaReadingUseCase.from_services("love_oracle", readings, generation)

    first = await use_case.create_preview(
        user.id,
        PersonaPreviewRequest(
            topic="boundaries",
            question="What boundary could help me stop guessing?",
            context="I have already sent one unanswered message.",
        ),
    )
    replay = await use_case.generate_existing_preview(first.reading_id, user.id)

    assert first.generation.status is ReadingGenerationStatus.COMPLETED
    assert not first.generation.idempotent
    assert replay.generation.status is ReadingGenerationStatus.COMPLETED
    assert replay.generation.idempotent
    assert len(llm.requests) == 1
    assert '"selected_symbols":[]' in llm.requests[0].user_prompt
    assert "private thoughts, feelings, intentions" in llm.requests[0].system_prompt
    assert "the other person's inner state" in llm.requests[0].user_prompt

    stored_result = await readings.load_result(first.reading_id, user.id)
    assert stored_result is not None
    assert stored_result["symbols"] == []
    async with payment_db() as session:
        reading = await session.get(Reading, first.reading_id)
        assert reading is not None
        assert reading.status == ReadingStatus.PREVIEW_READY.value
        assert reading.access_level == ReadingAccess.PREVIEW.value
        assert reading.engine_version == "symbolic-v1"
        assert reading.prompt_version == "love-oracle-v1"
        assert reading.schema_version == "reading-result-v1"


@pytest.mark.postgres
async def test_mind_reading_and_guaranteed_reunion_are_rejected_before_persistence(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("love-oracle-adversarial-key-material")
    async with payment_db.begin() as session:
        user = User(telegram_user_id=894002, first_name="LoveOracleAdversarial")
        persona = Persona(
            code="love_oracle",
            display_name="Love Oracle",
            prompt_version="love-oracle-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()

    readings = ReadingService(payment_db, cipher)
    generation = ReadingGenerationService(
        SqlAlchemyReadingGenerationStore(payment_db, cipher),
        MindReadingLoveOracleLLM(),
        max_repair_attempts=0,
    )
    use_case = PersonaReadingUseCase.from_services("love_oracle", readings, generation)

    outcome = await use_case.create_preview(
        user.id,
        PersonaPreviewRequest(
            topic="love",
            question="How should I think about the current distance?",
        ),
    )

    assert outcome.generation.status is ReadingGenerationStatus.FAILED
    assert outcome.generation.failure_code == "reading_unsafe_output"
    assert await readings.load_result(outcome.reading_id, user.id) is None
