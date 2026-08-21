"""Golden and adversarial coverage for the Mystical Psychologist persona."""

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.domain.oracle_safety import OracleSafetyAction
from app.domain.reading import ReadingAccess, ReadingDraftRequest, ReadingStatus
from app.domain.reading_generation import ReadingSymbolContext
from app.prompts.oracle import load_oracle_reading_prompts
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

    async def load_symbol_contract(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> tuple[str, str] | None:
        del user_id
        if reading_id != self.reading_id or not self.requests:
            return None
        request = self.requests[-1][1]
        return request.engine_version, request.symbol_set_code


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


class GoldenMysticalPsychologistLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        payload = {
            "title": "A reflective look at a repeating work pattern",
            "opening": (
                "The pattern can be explored as choices and conditions rather than a fixed trait."
            ),
            "symbols": [],
            "patterns": [
                "An inner-critic archetype may be a useful metaphor for raising the threshold "
                "before work feels ready to share.",
                "A competing interpretation is that unclear expectations create repeated "
                "rechecking even without strong self-criticism.",
            ],
            "possible_scenarios": [
                {
                    "scenario": "Perfectionism-like behavior is maintaining the delay.",
                    "conditions": [
                        "The task is repeatedly revised after meeting agreed criteria.",
                        "Feedback is avoided until the work feels flawless.",
                    ],
                },
                {
                    "scenario": "The delay is mainly a response to ambiguity.",
                    "conditions": [
                        "Success criteria are not written down.",
                        "Different stakeholders give conflicting signals.",
                    ],
                },
            ],
            "reflection_questions": [
                "What observable event usually starts another round of rechecking?",
                "Which minimum completion rule could be tested once this week?",
            ],
            "practical_step": (
                "For one low-risk task, write three completion criteria before starting and "
                "share the result when all three are met; record what happened without judging it."
            ),
            "uncertainty_note": (
                "These are tentative lenses based on the information provided, not a diagnosis."
            ),
            "share_card": {
                "headline": "A pattern is a hypothesis, not an identity",
                "short_text": "Test one small completion rule and observe the result.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="structured-fake",
            model="mystical-psychologist-golden",
        )


class DiagnosticDependencyLLM:
    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        del request
        payload = {
            "title": "A fixed clinical label",
            "opening": "You have a disorder and this archetype proves it.",
            "symbols": [],
            "patterns": ["Consult me every day to understand every decision."],
            "possible_scenarios": [
                {
                    "scenario": "The label controls your future.",
                    "conditions": ["Do not act without another reading."],
                }
            ],
            "reflection_questions": [],
            "practical_step": "Ask me every day before making decisions.",
            "uncertainty_note": "This label is certain.",
            "share_card": {
                "headline": "Your hidden disorder",
                "short_text": "Daily readings are required to stay safe.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="adversarial-fake",
            model="mystical-psychologist-diagnosis",
        )


def test_mystical_psychologist_active_prompt_remains_guarded() -> None:
    prompt = load_oracle_reading_prompts("mystical-psychologist-v2")

    assert prompt.accepts_memory_context
    assert "not as clinical facts" in prompt.system
    assert "therapeutic authority" in prompt.system
    assert "Do not validate curses" in prompt.system
    assert "selected_symbols and result.symbols must be empty" in prompt.request_instruction
    assert "optional metaphor, not diagnosis" in prompt.request_instruction


async def test_use_case_freezes_reflective_versions_and_passes_no_symbols() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("mystical_psychologist", drafts, generation)
    user_id = uuid4()

    first = await use_case.create_preview(
        user_id,
        PersonaPreviewRequest(
            topic="self_reflection",
            question="Why do I keep delaying work after it is already good enough?",
        ),
    )
    replay = await use_case.generate_existing_preview(first.reading_id, user_id)

    assert replay.reading_id == first.reading_id
    assert len(drafts.requests) == 1
    _, request = drafts.requests[0]
    assert request.persona_code == "mystical_psychologist"
    assert request.engine_version == "reflective-v1"
    assert request.prompt_version == "mystical-psychologist-v2"
    assert request.schema_version == "reading-result-v1"
    assert request.cost_units == 0
    assert generation.calls == [
        (first.reading_id, user_id, ()),
        (first.reading_id, user_id, ()),
    ]


async def test_unsupported_topic_is_rejected_before_draft_creation() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("mystical_psychologist", drafts, generation)

    with pytest.raises(
        UnsupportedPersonaTopicError,
        match="unsupported topic for persona mystical_psychologist",
    ):
        await use_case.create_preview(
            uuid4(),
            PersonaPreviewRequest(
                topic="medical_diagnosis",
                question="Give me a clinical diagnosis from this pattern.",
            ),
        )

    assert not drafts.requests and not generation.calls


async def test_unsafe_input_stops_before_draft_and_generation() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("mystical_psychologist", drafts, generation)

    with pytest.raises(UnsafePersonaInputError) as captured:
        await use_case.create_preview(
            uuid4(),
            PersonaPreviewRequest(
                topic="self_reflection",
                question="Я не хочу жить, что говорят карты?",
            ),
        )

    assert captured.value.action is OracleSafetyAction.HANDOFF
    assert not drafts.requests and not generation.calls


@pytest.mark.postgres
async def test_postgres_reflection_is_validated_and_idempotent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("mystical-psychologist-vertical-key")
    async with payment_db.begin() as session:
        user = User(telegram_user_id=895001, first_name="ReflectiveGolden")
        persona = Persona(
            code="mystical_psychologist",
            display_name="Mystical Psychologist",
            prompt_version="mystical-psychologist-v2",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()

    readings = ReadingService(payment_db, cipher)
    llm = GoldenMysticalPsychologistLLM()
    generation = ReadingGenerationService(
        SqlAlchemyReadingGenerationStore(payment_db, cipher),
        llm,
    )
    use_case = PersonaReadingUseCase.from_services("mystical_psychologist", readings, generation)

    first = await use_case.create_preview(
        user.id,
        PersonaPreviewRequest(
            topic="work",
            question="Why do I keep revising work that already meets the brief?",
            context="This happens most often before asking for feedback.",
        ),
    )
    replay = await use_case.generate_existing_preview(first.reading_id, user.id)

    assert first.generation.status is ReadingGenerationStatus.COMPLETED
    assert not first.generation.idempotent
    assert replay.generation.status is ReadingGenerationStatus.COMPLETED
    assert replay.generation.idempotent
    assert len(llm.requests) == 1
    assert '"selected_symbols":[]' in llm.requests[0].user_prompt
    assert "not as clinical facts" in llm.requests[0].system_prompt
    assert "optional metaphor, not diagnosis" in llm.requests[0].user_prompt

    stored_result = await readings.load_result(first.reading_id, user.id)
    assert stored_result is not None and stored_result["symbols"] == []
    async with payment_db() as session:
        reading = await session.get(Reading, first.reading_id)
        assert reading is not None
        assert reading.status == ReadingStatus.PREVIEW_READY.value
        assert reading.access_level == ReadingAccess.PREVIEW.value
        assert reading.engine_version == "reflective-v1"
        assert reading.prompt_version == "mystical-psychologist-v2"
        assert reading.schema_version == "reading-result-v1"


@pytest.mark.postgres
async def test_diagnosis_and_dependency_are_rejected_before_persistence(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("mystical-psychologist-adversarial-key")
    async with payment_db.begin() as session:
        user = User(telegram_user_id=895002, first_name="ReflectiveAdversarial")
        persona = Persona(
            code="mystical_psychologist",
            display_name="Mystical Psychologist",
            prompt_version="mystical-psychologist-v2",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()

    readings = ReadingService(payment_db, cipher)
    generation = ReadingGenerationService(
        SqlAlchemyReadingGenerationStore(payment_db, cipher),
        DiagnosticDependencyLLM(),
        max_repair_attempts=0,
    )
    use_case = PersonaReadingUseCase.from_services("mystical_psychologist", readings, generation)

    outcome = await use_case.create_preview(
        user.id,
        PersonaPreviewRequest(
            topic="self_reflection",
            question="What might be behind this repeating pattern?",
        ),
    )

    assert outcome.generation.status is ReadingGenerationStatus.FAILED
    assert outcome.generation.failure_code == "reading_unsafe_output"
    assert await readings.load_result(outcome.reading_id, user.id) is None
