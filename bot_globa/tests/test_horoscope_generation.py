"""Generation pipeline tests for fact-bound Horoscope readings."""

import json
from datetime import date
from uuid import UUID, uuid4

from app.domain.horoscope import (
    AstrologyReadingResult,
    HoroscopeFactBundle,
    HoroscopeScope,
)
from app.domain.horoscope_topic import HoroscopeTopic
from app.domain.reading import ReadingSymbolInput
from app.domain.reading_generation import (
    ReadingGenerationClaim,
    ReadingGenerationClaimStatus,
    ReadingGenerationContext,
    ReadingGenerationFinalizeStatus,
    StoredReadingResult,
)
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.services.horoscope_generation import (
    HoroscopeGenerationService,
    HoroscopeGenerationStatus,
)
from app.services.horoscope_storage import serialize_horoscope
from app.services.natal_chart import BirthProfileUnavailableError
from tests.horoscope_helpers import sample_fact_bundle, valid_horoscope_payload


class RecordingStore:
    def __init__(self, claim: ReadingGenerationClaim) -> None:
        self.claim = claim
        self.completed_payload: dict[str, object] | None = None
        self.completed_symbols: tuple[ReadingSymbolInput, ...] | None = None
        self.failure_code: str | None = None

    async def claim_preview(self, reading_id: UUID, user_id: UUID) -> ReadingGenerationClaim:
        return self.claim

    async def complete_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: tuple[ReadingSymbolInput, ...],
    ) -> ReadingGenerationFinalizeStatus:
        self.completed_payload = result
        self.completed_symbols = symbols
        return ReadingGenerationFinalizeStatus.COMPLETED

    async def fail_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
    ) -> ReadingGenerationFinalizeStatus:
        self.failure_code = failure_code
        return ReadingGenerationFinalizeStatus.COMPLETED


class RecordingFacts:
    def __init__(
        self,
        bundle: HoroscopeFactBundle | None,
        error: Exception | None = None,
    ) -> None:
        self.bundle = bundle
        self.error = error
        self.calls: list[tuple[UUID, HoroscopeScope, date | None]] = []

    async def calculate_for_user(
        self,
        user_id: UUID,
        scope: HoroscopeScope,
        *,
        reference_date: date | None = None,
    ) -> HoroscopeFactBundle:
        self.calls.append((user_id, scope, reference_date))
        if self.error is not None:
            raise self.error
        assert self.bundle is not None
        return self.bundle


class SequenceLLM:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.requests: list[LLMRequest] = []

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        payload = self.payloads[len(self.requests) - 1]
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="test",
            model="horoscope-test",
        )


def _claimed(
    reading_id: UUID,
    user_id: UUID,
    scope: HoroscopeScope = HoroscopeScope.NATAL_PROFILE,
    *,
    reference_date: date | None = None,
) -> ReadingGenerationClaim:
    topic = HoroscopeTopic.for_request(scope, reference_date)
    return ReadingGenerationClaim(
        ReadingGenerationClaimStatus.CLAIMED,
        context=ReadingGenerationContext(
            reading_id=reading_id,
            user_id=user_id,
            persona_code="astrologer",
            topic=topic.storage_value(),
            question="What pattern may help me choose a next step?",
            context="Keep the first experiment reversible.",
            engine_version="astrology-calculation-v1",
            prompt_version="astrologer-v2",
            schema_version="astrology-reading-result-v1",
        ),
    )


async def test_generation_sends_only_calculated_facts_and_persists_empty_symbols() -> None:
    reading_id, user_id = uuid4(), uuid4()
    bundle = sample_fact_bundle()
    store = RecordingStore(_claimed(reading_id, user_id))
    facts = RecordingFacts(bundle)
    llm = SequenceLLM([valid_horoscope_payload(bundle)])

    outcome = await HoroscopeGenerationService(store, llm, facts).generate_preview(
        reading_id,
        user_id,
    )

    assert outcome.status is HoroscopeGenerationStatus.COMPLETED
    assert outcome.result is not None and outcome.facts == bundle
    assert store.completed_payload == serialize_horoscope(outcome.result, bundle)
    assert store.completed_symbols == ()
    assert facts.calls == [(user_id, HoroscopeScope.NATAL_PROFILE, None)]
    assert len(llm.requests) == 1
    prompt = llm.requests[0].user_prompt
    assert bundle.digest() in prompt
    assert bundle.facts[0].fact_id in prompt
    assert "1991-04-17" not in prompt
    assert "Amsterdam" not in prompt
    assert '"birth_date":' not in prompt
    assert '"birth_time":' not in prompt


async def test_generation_reuses_persisted_forecast_anchor_for_fact_calculation() -> None:
    reading_id, user_id = uuid4(), uuid4()
    anchor_source = date(2026, 8, 7)
    store = RecordingStore(
        _claimed(
            reading_id,
            user_id,
            HoroscopeScope.MONTH_FORECAST,
            reference_date=anchor_source,
        )
    )
    facts = RecordingFacts(
        None,
        BirthProfileUnavailableError("active birth profile is required"),
    )

    outcome = await HoroscopeGenerationService(store, SequenceLLM([]), facts).generate_preview(
        reading_id,
        user_id,
    )

    assert outcome.status is HoroscopeGenerationStatus.FAILED
    assert outcome.failure_code == "birth_profile_unavailable"
    assert facts.calls == [
        (user_id, HoroscopeScope.MONTH_FORECAST, date(2026, 8, 1)),
    ]


async def test_generation_repairs_one_invalid_fact_claim_without_exposing_payload() -> None:
    reading_id, user_id = uuid4(), uuid4()
    bundle = sample_fact_bundle()
    invalid = valid_horoscope_payload(bundle)
    invalid["overview"] = "Sun in Aries at 12° guarantees the result."
    valid = valid_horoscope_payload(bundle)
    store = RecordingStore(_claimed(reading_id, user_id))
    llm = SequenceLLM([invalid, valid])

    outcome = await HoroscopeGenerationService(store, llm, RecordingFacts(bundle)).generate_preview(
        reading_id,
        user_id,
    )

    assert outcome.status is HoroscopeGenerationStatus.COMPLETED
    assert outcome.attempt_count == 2 and outcome.repair_used
    assert len(llm.requests) == 2 and llm.requests[1].repair
    assert "overview:raw_astrology_claim" in llm.requests[1].user_prompt
    correction = llm.requests[1].user_prompt.split("CORRECTION_INSTRUCTION:", 1)[1]
    assert "Sun in Aries" not in correction


async def test_generation_fails_after_second_fact_integrity_violation() -> None:
    reading_id, user_id = uuid4(), uuid4()
    bundle = sample_fact_bundle()
    invalid = valid_horoscope_payload(bundle)
    invalid["facts_digest"] = "0" * 64
    store = RecordingStore(_claimed(reading_id, user_id))
    llm = SequenceLLM([invalid, invalid])

    outcome = await HoroscopeGenerationService(store, llm, RecordingFacts(bundle)).generate_preview(
        reading_id,
        user_id,
    )

    assert outcome.status is HoroscopeGenerationStatus.FAILED
    assert outcome.failure_code == "horoscope_invalid_semantics"
    assert outcome.attempt_count == 2
    assert store.completed_payload is None
    assert store.failure_code == "horoscope_invalid_semantics"


async def test_ready_replay_restores_facts_and_skips_calculation_and_llm() -> None:
    reading_id, user_id = uuid4(), uuid4()
    bundle = sample_fact_bundle()
    result = AstrologyReadingResult.model_validate_json(json.dumps(valid_horoscope_payload(bundle)))
    store = RecordingStore(
        ReadingGenerationClaim(
            ReadingGenerationClaimStatus.READY,
            ready=StoredReadingResult(
                payload=serialize_horoscope(result, bundle),
                symbols=(),
            ),
        )
    )
    facts = RecordingFacts(None)
    llm = SequenceLLM([])

    outcome = await HoroscopeGenerationService(store, llm, facts).generate_preview(
        reading_id,
        user_id,
    )

    assert outcome.status is HoroscopeGenerationStatus.COMPLETED
    assert outcome.idempotent and outcome.result == result
    assert outcome.facts == bundle
    assert facts.calls == [] and llm.requests == []


async def test_ready_replay_rejects_tampered_fact_bundle() -> None:
    reading_id, user_id = uuid4(), uuid4()
    bundle = sample_fact_bundle()
    result = AstrologyReadingResult.model_validate_json(json.dumps(valid_horoscope_payload(bundle)))
    envelope = serialize_horoscope(result, bundle)
    facts_payload = envelope["facts"]
    assert isinstance(facts_payload, dict)
    facts_payload["natal_engine_version"] = "tampered-engine"
    store = RecordingStore(
        ReadingGenerationClaim(
            ReadingGenerationClaimStatus.READY,
            ready=StoredReadingResult(payload=envelope, symbols=()),
        )
    )

    outcome = await HoroscopeGenerationService(
        store,
        SequenceLLM([]),
        RecordingFacts(None),
    ).generate_preview(reading_id, user_id)

    assert outcome.status is HoroscopeGenerationStatus.CORRUPTED_RESULT


async def test_missing_or_revoked_birth_profile_fails_before_llm() -> None:
    reading_id, user_id = uuid4(), uuid4()
    store = RecordingStore(_claimed(reading_id, user_id))
    facts = RecordingFacts(None, BirthProfileUnavailableError("active birth profile is required"))
    llm = SequenceLLM([])

    outcome = await HoroscopeGenerationService(store, llm, facts).generate_preview(
        reading_id,
        user_id,
    )

    assert outcome.status is HoroscopeGenerationStatus.FAILED
    assert outcome.failure_code == "birth_profile_unavailable"
    assert store.failure_code == "birth_profile_unavailable"
    assert llm.requests == []
