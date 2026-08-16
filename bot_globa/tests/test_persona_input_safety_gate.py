"""Unsafe intake must never be persisted or sent to a prompt, for any persona."""

from uuid import UUID, uuid4

import pytest

from app.db.reading_models import Reading
from app.domain.oracle_safety import OracleRiskCategory, OracleSafetyAction
from app.domain.reading import ReadingDraftRequest
from app.domain.reading_generation import ReadingSymbolContext
from app.services.persona_reading import (
    PersonaPreviewRequest,
    PersonaReadingUseCase,
    UnsafePersonaInputError,
)
from app.services.reading_generation import ReadingGenerationResult

# (persona_code, a topic that persona supports)
PERSONA_TOPICS = [
    ("tarot_reader", "general_forecast"),
    ("love_oracle", "love"),
    ("mystical_psychologist", "self_reflection"),
]
personas = pytest.mark.parametrize(
    ("persona_code", "topic"), PERSONA_TOPICS, ids=[code for code, _ in PERSONA_TOPICS]
)


class ForbiddenDraftService:
    calls = 0

    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading:
        self.calls += 1
        raise AssertionError("unsafe input must not be persisted")

    async def load_symbol_contract(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> tuple[str, str] | None:
        raise AssertionError("unsafe input must not reach persistence")


class ForbiddenGenerationService:
    calls = 0

    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult:
        self.calls += 1
        raise AssertionError("unsafe input must not reach generation")


@personas
@pytest.mark.asyncio
async def test_self_harm_is_rejected_before_draft_creation(
    persona_code: str,
    topic: str,
) -> None:
    drafts = ForbiddenDraftService()
    generation = ForbiddenGenerationService()
    use_case = PersonaReadingUseCase(persona_code, drafts, generation)

    with pytest.raises(UnsafePersonaInputError) as captured:
        await use_case.create_preview(
            uuid4(),
            PersonaPreviewRequest(
                topic=topic,
                question="Я не хочу жить. Что говорят карты?",
            ),
        )

    assert captured.value.action is OracleSafetyAction.HANDOFF
    assert captured.value.categories == (OracleRiskCategory.SELF_HARM,)
    assert drafts.calls == 0
    assert generation.calls == 0
    assert "Я не хочу жить" not in str(captured.value)


@personas
@pytest.mark.asyncio
async def test_stalking_request_is_blocked_before_draft_creation(
    persona_code: str,
    topic: str,
) -> None:
    drafts = ForbiddenDraftService()
    generation = ForbiddenGenerationService()
    use_case = PersonaReadingUseCase(persona_code, drafts, generation)

    with pytest.raises(UnsafePersonaInputError) as captured:
        await use_case.create_preview(
            uuid4(),
            PersonaPreviewRequest(
                topic=topic,
                question="Скажи, как выследить бывшую",
            ),
        )

    assert captured.value.action is OracleSafetyAction.BLOCK
    assert captured.value.categories == (OracleRiskCategory.VIOLENCE_OR_STALKING,)
    assert drafts.calls == 0
    assert generation.calls == 0


@pytest.mark.asyncio
async def test_the_astrology_persona_cannot_be_built_by_this_use_case() -> None:
    """A birth-data persona must not silently lose its calculation engine."""
    from app.services.persona_reading import PersonaConfigurationError

    with pytest.raises(PersonaConfigurationError, match="requires the astrology use case"):
        PersonaReadingUseCase("astrologer", ForbiddenDraftService(), ForbiddenGenerationService())
