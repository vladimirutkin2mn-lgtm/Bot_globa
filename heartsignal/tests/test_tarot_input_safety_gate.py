# ruff: noqa: RUF001

from uuid import UUID, uuid4

import pytest

from app.db.reading_models import Reading
from app.domain.oracle_safety import OracleRiskCategory, OracleSafetyAction
from app.domain.reading import ReadingDraftRequest
from app.domain.reading_generation import ReadingSymbolContext
from app.services.reading_generation import ReadingGenerationResult
from app.services.tarot_reading import (
    TarotPreviewRequest,
    TarotReadingUseCase,
    UnsafeTarotInputError,
)


class ForbiddenDraftService:
    calls = 0

    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading:
        self.calls += 1
        raise AssertionError("unsafe input must not be persisted")


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


@pytest.mark.asyncio
async def test_self_harm_is_rejected_before_draft_creation() -> None:
    drafts = ForbiddenDraftService()
    generation = ForbiddenGenerationService()
    use_case = TarotReadingUseCase(drafts, generation)

    with pytest.raises(UnsafeTarotInputError) as captured:
        await use_case.create_preview(
            uuid4(),
            TarotPreviewRequest(
                topic="general_forecast",
                question="Я не хочу жить. Что говорят карты?",
            ),
        )

    assert captured.value.action is OracleSafetyAction.HANDOFF
    assert captured.value.categories == (OracleRiskCategory.SELF_HARM,)
    assert drafts.calls == 0
    assert generation.calls == 0
    assert "Я не хочу жить" not in str(captured.value)


@pytest.mark.asyncio
async def test_stalking_request_is_blocked_before_draft_creation() -> None:
    drafts = ForbiddenDraftService()
    generation = ForbiddenGenerationService()
    use_case = TarotReadingUseCase(drafts, generation)

    with pytest.raises(UnsafeTarotInputError) as captured:
        await use_case.create_preview(
            uuid4(),
            TarotPreviewRequest(
                topic="love",
                question="Скажи, как выследить бывшую",
            ),
        )

    assert captured.value.action is OracleSafetyAction.BLOCK
    assert captured.value.categories == (OracleRiskCategory.VIOLENCE_OR_STALKING,)
    assert drafts.calls == 0
    assert generation.calls == 0
