"""PostgreSQL vertical coverage for calculated, fact-bound Horoscope readings."""

import json
from datetime import date, time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.horoscope_renderer import HoroscopeRenderer
from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.domain.birth_profile import BirthProfileInput
from app.domain.horoscope import HoroscopeScope
from app.domain.reading import ReadingAccess, ReadingStatus
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.repositories.reading_generation import SqlAlchemyReadingGenerationStore
from app.services.birth_profile import BirthProfileService
from app.services.horoscope_facts import HoroscopeFactService
from app.services.horoscope_generation import (
    HoroscopeGenerationService,
    HoroscopeGenerationStatus,
)
from app.services.horoscope_reading import (
    HoroscopePreviewRequest,
    HoroscopeReadingUseCase,
)
from app.services.horoscope_storage import deserialize_horoscope
from app.services.natal_chart import (
    AstronomyEngineNatalChartCalculator,
    ConsentedNatalChartService,
)
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


class GoldenHoroscopeLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        input_payload = _json_section(request.user_prompt, "INPUT_JSON:", "FACT_BUNDLE_JSON:")
        facts_payload = _json_section(request.user_prompt, "FACT_BUNDLE_JSON:")
        facts = facts_payload["facts"]
        limitations = facts_payload["limitations"]
        assert isinstance(facts, list) and facts
        assert isinstance(limitations, list)
        first_fact = facts[0]
        assert isinstance(first_fact, dict)
        fact_id = first_fact["fact_id"]
        payload = {
            "title": "A reflective astrology profile",
            "scope": input_payload["scope"],
            "facts_digest": input_payload["facts_digest"],
            "overview": (
                "Several calculated patterns may support slower observation before action."
            ),
            "interpretations": [
                {
                    "fact_ids": [fact_id],
                    "text": (
                        "This pattern may be useful as a prompt to balance initiative with "
                        "patience."
                    ),
                }
            ],
            "themes": ["Measured pacing may make the next choice easier to evaluate."],
            "possible_scenarios": [
                {
                    "scenario": (
                        "A reversible experiment may reveal which direction feels sustainable."
                    ),
                    "conditions": ["Keep the first step small and observe the response."],
                }
            ],
            "reflection_questions": ["What evidence would make the next step feel proportionate?"],
            "practical_step": (
                "Write down one reversible action and one boundary before deciding."
            ),
            "limitations": limitations,
            "uncertainty_note": (
                "This interpretation cannot predict events or replace your judgment."
            ),
            "share_card": {
                "headline": "A reflective pattern",
                "short_text": "Pause, observe, and choose one reversible next step.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="structured-fake",
            model="horoscope-golden",
        )


class AlteredChartHoroscopeLLM:
    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        input_payload = _json_section(request.user_prompt, "INPUT_JSON:", "FACT_BUNDLE_JSON:")
        facts_payload = _json_section(request.user_prompt, "FACT_BUNDLE_JSON:")
        limitations = facts_payload["limitations"]
        facts = facts_payload["facts"]
        assert isinstance(limitations, list)
        assert isinstance(facts, list) and facts and isinstance(facts[0], dict)
        payload = {
            "title": "A changed chart",
            "scope": input_payload["scope"],
            "facts_digest": "0" * 64,
            "overview": "Sun in Aries at 12° guarantees a decisive result.",
            "interpretations": [
                {
                    "fact_ids": [facts[0]["fact_id"]],
                    "text": "This will definitely happen during the selected period.",
                }
            ],
            "themes": ["A guaranteed outcome."],
            "possible_scenarios": [
                {
                    "scenario": "The event will certainly happen.",
                    "conditions": ["No condition can change it."],
                }
            ],
            "reflection_questions": [],
            "practical_step": "Wait for the guaranteed result.",
            "limitations": limitations,
            "uncertainty_note": "There is no uncertainty.",
            "share_card": {
                "headline": "A certain future",
                "short_text": "The chart guarantees the outcome.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="adversarial-fake",
            model="horoscope-altered-chart",
        )


def _json_section(
    prompt: str,
    marker: str,
    next_marker: str | None = None,
) -> dict[str, object]:
    value = prompt.split(marker, 1)[1]
    if next_marker is not None:
        value = value.split(next_marker, 1)[0]
    parsed = json.loads(value.strip())
    assert isinstance(parsed, dict)
    return parsed


def _private_profile() -> BirthProfileInput:
    return BirthProfileInput(
        birth_date=date(1991, 4, 17),
        birth_time=time(8, 35),
        birth_place="Amsterdam private birth marker",
        timezone="Europe/Amsterdam",
        latitude=52.367573,
        longitude=4.904139,
        utc_offset_minutes=120,
    )


async def _setup(
    payment_db: async_sessionmaker[AsyncSession],
    telegram_id: int,
) -> tuple[User, AESGCMSensitiveContentCipher, BirthProfileService]:
    cipher = AESGCMSensitiveContentCipher(f"horoscope-vertical-key-{telegram_id}")
    async with payment_db.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Horoscope")
        persona = Persona(
            code="astrologer",
            display_name="Astrologer",
            prompt_version="astrologer-v1",
            schema_version="astrology-reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()
    profiles = BirthProfileService(payment_db, cipher)
    await profiles.grant_consent(user.id)
    await profiles.save(user.id, _private_profile())
    return user, cipher, profiles


def _generation(
    payment_db: async_sessionmaker[AsyncSession],
    cipher: AESGCMSensitiveContentCipher,
    profiles: BirthProfileService,
    llm: GoldenHoroscopeLLM | AlteredChartHoroscopeLLM,
    *,
    max_repair_attempts: int = 1,
) -> HoroscopeGenerationService:
    charts = ConsentedNatalChartService(
        profiles,
        AstronomyEngineNatalChartCalculator(),
    )
    facts = HoroscopeFactService(charts)
    return HoroscopeGenerationService(
        SqlAlchemyReadingGenerationStore(payment_db, cipher),
        llm,
        facts,
        max_repair_attempts=max_repair_attempts,
    )


async def test_postgres_horoscope_is_fact_bound_rendered_and_idempotent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, cipher, profiles = await _setup(payment_db, 897001)
    readings = ReadingService(payment_db, cipher)
    llm = GoldenHoroscopeLLM()
    use_case = HoroscopeReadingUseCase.from_services(
        readings,
        _generation(payment_db, cipher, profiles, llm),
    )

    first = await use_case.create_preview(
        user.id,
        HoroscopePreviewRequest(
            topic=HoroscopeScope.NATAL_PROFILE,
            question="Which pattern may help me make a measured choice?",
            context="I want the first step to remain reversible.",
        ),
    )
    replay = await use_case.generate_existing_preview(first.reading_id, user.id)

    assert first.generation.status is HoroscopeGenerationStatus.COMPLETED
    assert not first.generation.idempotent
    assert replay.generation.status is HoroscopeGenerationStatus.COMPLETED
    assert replay.generation.idempotent
    assert len(llm.requests) == 1
    prompt = llm.requests[0].user_prompt
    for private_marker in (
        "1991-04-17",
        "08:35",
        "Amsterdam private birth marker",
        "Europe/Amsterdam",
        "52.367573",
        "4.904139",
        '"birth_date"',
        '"birth_time"',
        '"birth_place"',
        '"timezone"',
    ):
        assert private_marker not in prompt

    assert first.generation.result is not None and first.generation.facts is not None
    assert replay.generation.result is not None and replay.generation.facts is not None
    assert replay.generation.facts == first.generation.facts
    rendered = HoroscopeRenderer().render(
        replay.generation.result,
        replay.generation.facts,
    )
    assert "Асцендент" in rendered.text
    assert "°" in rendered.text
    assert "Amsterdam private birth marker" not in rendered.text

    stored_envelope = await readings.load_result(first.reading_id, user.id)
    assert stored_envelope is not None
    stored_result, stored_facts = deserialize_horoscope(stored_envelope)
    assert stored_result == first.generation.result
    assert stored_facts == first.generation.facts
    assert stored_result.facts_digest == stored_facts.digest()
    async with payment_db() as session:
        reading = await session.get(Reading, first.reading_id)
        assert reading is not None
        assert reading.status == ReadingStatus.PREVIEW_READY.value
        assert reading.access_level == ReadingAccess.PREVIEW.value
        assert reading.engine_version == "astrology-calculation-v1"
        assert reading.prompt_version == "astrologer-v1"
        assert reading.schema_version == "astrology-reading-result-v1"


async def test_altered_chart_claim_is_rejected_before_persistence(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, cipher, profiles = await _setup(payment_db, 897002)
    readings = ReadingService(payment_db, cipher)
    use_case = HoroscopeReadingUseCase.from_services(
        readings,
        _generation(
            payment_db,
            cipher,
            profiles,
            AlteredChartHoroscopeLLM(),
            max_repair_attempts=0,
        ),
    )

    outcome = await use_case.create_preview(
        user.id,
        HoroscopePreviewRequest(
            topic=HoroscopeScope.MONTH_FORECAST,
            question="Which themes may be useful to observe this month?",
        ),
    )

    assert outcome.generation.status is HoroscopeGenerationStatus.FAILED
    assert outcome.generation.failure_code == "horoscope_invalid_semantics"
    assert await readings.load_result(outcome.reading_id, user.id) is None
