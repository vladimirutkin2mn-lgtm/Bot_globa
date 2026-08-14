"""Application and prompt boundary tests for the Horoscope persona."""

from datetime import date
from uuid import UUID, uuid4

import pytest

from app.db.reading_models import Reading
from app.domain.horoscope import HoroscopeScope
from app.domain.horoscope_topic import HoroscopeTopic
from app.domain.oracle_safety import OracleSafetyAction
from app.domain.reading import ReadingDraftRequest
from app.prompts.horoscope import load_horoscope_prompts
from app.services.horoscope_generation import (
    HoroscopeGenerationResult,
    HoroscopeGenerationStatus,
)
from app.services.horoscope_reading import (
    HoroscopePreviewRequest,
    HoroscopeReadingUseCase,
    UnsafeHoroscopeInputError,
)


class CapturingDraftService:
    def __init__(self) -> None:
        self.reading_id = uuid4()
        self.requests: list[tuple[UUID, ReadingDraftRequest]] = []

    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading:
        self.requests.append((user_id, request))
        return Reading(id=self.reading_id)


class CapturingHoroscopeGeneration:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> HoroscopeGenerationResult:
        self.calls.append((reading_id, user_id))
        return HoroscopeGenerationResult(HoroscopeGenerationStatus.COMPLETED)


def test_astrologer_legacy_prompt_remains_available() -> None:
    prompt = load_horoscope_prompts("astrologer-v1")

    assert "FACT_BUNDLE_JSON" in prompt.system
    assert "only permitted source for astrology facts" in prompt.system
    assert "Reference facts only by their exact fact_id" in prompt.system
    assert "Do not write planet names" in prompt.system
    assert "Copy the scope and facts_digest exactly" in prompt.request_instruction
    assert "unknown birth time" in prompt.request_instruction


async def test_use_case_freezes_astrology_versions_without_raw_birth_fields() -> None:
    drafts = CapturingDraftService()
    generation = CapturingHoroscopeGeneration()
    use_case = HoroscopeReadingUseCase(drafts, generation)
    user_id = uuid4()

    first = await use_case.create_preview(
        user_id,
        HoroscopePreviewRequest(
            topic=HoroscopeScope.WEEK_FORECAST,
            question="Which themes may be useful to observe this week?",
            context="I want to keep my next choice reversible.",
            reference_date=date(2026, 8, 7),
        ),
    )
    replay = await use_case.generate_existing_preview(first.reading_id, user_id)

    assert replay.reading_id == first.reading_id
    assert len(drafts.requests) == 1
    _, request = drafts.requests[0]
    assert request.persona_code == "astrologer"
    assert request.topic == "week_forecast__2026_08_03"
    assert HoroscopeTopic.parse(request.topic) == HoroscopeTopic(
        HoroscopeScope.WEEK_FORECAST,
        date(2026, 8, 3),
    )
    assert request.engine_version == "astrology-calculation-v1"
    assert request.prompt_version == "astrologer-v2"
    assert request.schema_version == "astrology-reading-result-v1"
    assert request.cost_units == 0
    assert generation.calls == [
        (first.reading_id, user_id),
        (first.reading_id, user_id),
    ]


async def test_unsafe_input_stops_before_draft_fact_calculation_and_llm() -> None:
    drafts = CapturingDraftService()
    generation = CapturingHoroscopeGeneration()
    use_case = HoroscopeReadingUseCase(drafts, generation)

    with pytest.raises(UnsafeHoroscopeInputError) as captured:
        await use_case.create_preview(
            uuid4(),
            HoroscopePreviewRequest(
                topic=HoroscopeScope.LOVE,
                question="I want to kill myself if this person does not return.",
            ),
        )

    assert captured.value.action is OracleSafetyAction.HANDOFF
    assert not drafts.requests and not generation.calls
