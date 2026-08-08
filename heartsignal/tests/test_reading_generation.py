"""Orchestration coverage for structured reading generation and one safe repair."""

import asyncio
import json
import logging
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from app.domain.reading import ReadingSymbolInput, SymbolOrientation
from app.domain.reading_generation import (
    ReadingGenerationClaim,
    ReadingGenerationClaimStatus,
    ReadingGenerationContext,
    ReadingGenerationFinalizeStatus,
    ReadingSymbolContext,
    StoredReadingResult,
)
from app.prompts.reading import (
    ReadingPromptNotFoundError,
    ReadingPromptSet,
    load_reading_prompts,
)
from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMCompletion,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
    LLMUnexpectedError,
)
from app.services.reading_generation import (
    ReadingGenerationResult,
    ReadingGenerationService,
    ReadingGenerationStatus,
)

SECRET_QUESTION = "private-question-marker"
PRIOR_OUTPUT_MARKER = "invalid-prior-output-marker"


def _symbols() -> tuple[ReadingSymbolContext, ...]:
    return (
        ReadingSymbolContext(
            symbol=ReadingSymbolInput(
                symbol_id="major_20",
                position="current_influence",
                orientation=SymbolOrientation.REVERSED,
                catalog_version="tarot-major-v1",
            ),
            display_name="Judgement",
            interpretation_theme="Delayed review and resistance to an honest assessment.",
        ),
        ReadingSymbolContext(
            symbol=ReadingSymbolInput(
                symbol_id="major_07",
                position="hidden_factor",
                orientation=SymbolOrientation.UPRIGHT,
                catalog_version="tarot-major-v1",
            ),
            display_name="The Chariot",
            interpretation_theme="Direction, agency and disciplined movement.",
        ),
    )


def _valid_payload(symbols: tuple[ReadingSymbolContext, ...] | None = None) -> str:
    selected = symbols or _symbols()
    return json.dumps(
        {
            "title": "A decision that benefits from a slower review",
            "opening": "The spread highlights momentum and deliberate evaluation.",
            "symbols": [
                {
                    "symbol_id": item.symbol.symbol_id,
                    "position": item.symbol.position,
                    "orientation": item.symbol.orientation.value,
                    "interpretation": f"A bounded interpretation of {item.display_name}.",
                }
                for item in selected
            ],
            "patterns": ["Momentum may be replacing comparison."],
            "possible_scenarios": [
                {
                    "scenario": "A pause makes the trade-offs easier to compare.",
                    "conditions": ["Write down the reversible parts of each option."],
                }
            ],
            "reflection_questions": ["Which choice protects the value that matters most?"],
            "practical_step": "Compare the two options in writing before committing.",
            "uncertainty_note": "The cards cannot determine which external event will occur.",
            "share_card": {
                "headline": "Your choice asks for a slower review",
                "short_text": "Compare values before momentum makes the choice.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
    )


class MemoryStore:
    def __init__(self, claim: ReadingGenerationClaim | None = None) -> None:
        self.reading_id = uuid4()
        self.user_id = uuid4()
        self.claim = claim or ReadingGenerationClaim(
            ReadingGenerationClaimStatus.CLAIMED,
            context=ReadingGenerationContext(
                reading_id=self.reading_id,
                user_id=self.user_id,
                persona_code="tarot_reader",
                topic="decision",
                question=SECRET_QUESTION,
                context="Two reversible work options are available.",
                engine_version="symbolic-v1",
                prompt_version="tarot-reader-v1",
                schema_version="reading-result-v1",
            ),
        )
        self.complete_writes = 0
        self.failure_writes = 0
        self.result: dict[str, object] | None = None
        self.symbols: tuple[ReadingSymbolInput, ...] = ()
        self.failure_code: str | None = None
        self.complete_status = ReadingGenerationFinalizeStatus.COMPLETED
        self.fail_status = ReadingGenerationFinalizeStatus.COMPLETED

    async def claim_preview(self, reading_id: UUID, user_id: UUID) -> ReadingGenerationClaim:
        assert (reading_id, user_id) == (self.reading_id, self.user_id)
        return self.claim

    async def complete_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: tuple[ReadingSymbolInput, ...],
    ) -> ReadingGenerationFinalizeStatus:
        assert (reading_id, user_id) == (self.reading_id, self.user_id)
        self.complete_writes += 1
        if self.complete_status is ReadingGenerationFinalizeStatus.COMPLETED:
            self.result = result
            self.symbols = symbols
        return self.complete_status

    async def fail_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
    ) -> ReadingGenerationFinalizeStatus:
        assert (reading_id, user_id) == (self.reading_id, self.user_id)
        self.failure_writes += 1
        self.failure_code = failure_code
        return self.fail_status


class ControlledLLM:
    def __init__(self, *outputs: str | Exception) -> None:
        self.outputs = list(outputs)
        self.requests: list[LLMRequest] = []

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return LLMCompletion(
            payload=output,
            provider="controlled",
            model="oracle-test-model",
            provider_request_id="request-1",
            input_tokens=11,
            output_tokens=22,
            latency_ms=33,
        )


def _service(
    store: MemoryStore,
    llm: ControlledLLM,
    *,
    max_repair_attempts: int = 1,
    prompt_loader: Callable[[str], ReadingPromptSet] = load_reading_prompts,
) -> ReadingGenerationService:
    return ReadingGenerationService(
        store,
        llm,
        max_repair_attempts=max_repair_attempts,
        prompt_loader=prompt_loader,
    )


async def _run(
    store: MemoryStore,
    llm: ControlledLLM,
    *,
    max_repair_attempts: int = 1,
) -> ReadingGenerationResult:
    service = _service(store, llm, max_repair_attempts=max_repair_attempts)
    return await service.generate_preview(store.reading_id, store.user_id, _symbols())


async def test_valid_first_response_persists_only_validated_result() -> None:
    store = MemoryStore()
    llm = ControlledLLM(_valid_payload())

    result = await _run(store, llm)

    assert result.status is ReadingGenerationStatus.COMPLETED
    assert result.attempt_count == 1 and not result.repair_used
    assert result.provider == "controlled" and result.model == "oracle-test-model"
    assert store.complete_writes == 1 and store.failure_writes == 0
    assert store.result is not None and len(store.symbols) == 2
    assert len(llm.requests) == 1 and not llm.requests[0].repair


async def test_invalid_first_output_is_regenerated_once_without_prior_payload() -> None:
    store = MemoryStore()
    llm = ControlledLLM(
        json.dumps({"title": PRIOR_OUTPUT_MARKER}),
        _valid_payload(),
    )

    result = await _run(store, llm)

    assert result.status is ReadingGenerationStatus.COMPLETED
    assert result.attempt_count == 2 and result.repair_used
    assert len(llm.requests) == 2 and llm.requests[1].repair
    assert PRIOR_OUTPUT_MARKER not in llm.requests[1].user_prompt
    assert SECRET_QUESTION in llm.requests[1].user_prompt
    assert store.complete_writes == 1 and store.failure_writes == 0


async def test_two_invalid_outputs_fail_without_persisting_partial_result() -> None:
    store = MemoryStore()
    llm = ControlledLLM(
        json.dumps({"title": "incomplete"}),
        json.dumps({"title": "still incomplete"}),
    )

    result = await _run(store, llm)

    assert result.status is ReadingGenerationStatus.FAILED
    assert result.failure_code == "reading_invalid_schema"
    assert result.attempt_count == 2 and result.repair_used
    assert store.complete_writes == 0 and store.result is None
    assert store.failure_writes == 1 and store.failure_code == result.failure_code


async def test_application_selected_symbols_cannot_be_replaced() -> None:
    store = MemoryStore()
    payload = json.loads(_valid_payload())
    payload["symbols"][0]["symbol_id"] = "major_01"
    llm = ControlledLLM(json.dumps(payload))

    result = await _run(store, llm, max_repair_attempts=0)

    assert result.status is ReadingGenerationStatus.FAILED
    assert result.failure_code == "reading_invalid_semantics"
    assert store.complete_writes == 0 and store.failure_writes == 1


@pytest.mark.parametrize(
    ("error", "failure_code"),
    [
        (LLMTimeoutError(), "llm_timeout"),
        (LLMRateLimitError(), "llm_rate_limited"),
        (LLMAuthenticationError(), "llm_authentication_error"),
        (LLMInvalidRequestError(), "llm_invalid_request"),
        (LLMTransientError(), "llm_transient_error"),
        (LLMUnexpectedError(), "unexpected_provider_error"),
    ],
)
async def test_provider_failures_are_not_repaired(
    error: Exception,
    failure_code: str,
) -> None:
    store = MemoryStore()
    llm = ControlledLLM(error)

    result = await _run(store, llm)

    assert result.status is ReadingGenerationStatus.FAILED
    assert result.failure_code == failure_code
    assert len(llm.requests) == 1
    assert store.complete_writes == 0 and store.failure_writes == 1


async def test_ready_result_replays_without_provider_call_or_new_write() -> None:
    symbols = tuple(item.symbol for item in _symbols())
    claim = ReadingGenerationClaim(
        ReadingGenerationClaimStatus.READY,
        ready=StoredReadingResult(json.loads(_valid_payload()), symbols),
    )
    store = MemoryStore(claim)
    llm = ControlledLLM()

    result = await _run(store, llm)

    assert result.status is ReadingGenerationStatus.COMPLETED and result.idempotent
    assert not llm.requests
    assert store.complete_writes == 0 and store.failure_writes == 0


async def test_corrupted_ready_result_never_calls_provider() -> None:
    symbols = tuple(item.symbol for item in _symbols())
    claim = ReadingGenerationClaim(
        ReadingGenerationClaimStatus.READY,
        ready=StoredReadingResult({"title": "corrupted"}, symbols),
    )
    store = MemoryStore(claim)
    llm = ControlledLLM()

    result = await _run(store, llm)

    assert result.status is ReadingGenerationStatus.CORRUPTED_RESULT
    assert not llm.requests and store.complete_writes == 0


@pytest.mark.parametrize(
    ("claim_status", "service_status"),
    [
        (
            ReadingGenerationClaimStatus.ALREADY_PROCESSING,
            ReadingGenerationStatus.ALREADY_PROCESSING,
        ),
        (ReadingGenerationClaimStatus.NOT_READY, ReadingGenerationStatus.NOT_READY),
        (
            ReadingGenerationClaimStatus.PERSONA_DISABLED,
            ReadingGenerationStatus.PERSONA_DISABLED,
        ),
        (ReadingGenerationClaimStatus.DELETED, ReadingGenerationStatus.DELETED),
        (ReadingGenerationClaimStatus.NOT_FOUND, ReadingGenerationStatus.NOT_FOUND),
        (
            ReadingGenerationClaimStatus.CORRUPTED_RESULT,
            ReadingGenerationStatus.CORRUPTED_RESULT,
        ),
    ],
)
async def test_non_claimable_readings_never_call_provider(
    claim_status: ReadingGenerationClaimStatus,
    service_status: ReadingGenerationStatus,
) -> None:
    store = MemoryStore(ReadingGenerationClaim(claim_status))
    llm = ControlledLLM()

    result = await _run(store, llm)

    assert result.status is service_status
    assert not llm.requests and store.complete_writes == 0 and store.failure_writes == 0


async def test_schema_version_mismatch_fails_before_provider_call() -> None:
    store = MemoryStore()
    assert store.claim.context is not None
    original = store.claim.context
    store.claim = ReadingGenerationClaim(
        ReadingGenerationClaimStatus.CLAIMED,
        context=ReadingGenerationContext(
            reading_id=original.reading_id,
            user_id=original.user_id,
            persona_code=original.persona_code,
            topic=original.topic,
            question=original.question,
            context=original.context,
            engine_version=original.engine_version,
            prompt_version=original.prompt_version,
            schema_version="reading-result-v999",
        ),
    )
    llm = ControlledLLM()

    result = await _run(store, llm)

    assert result.failure_code == "schema_version_mismatch"
    assert not llm.requests and store.failure_writes == 1


async def test_missing_prompt_fails_before_provider_call() -> None:
    store = MemoryStore()
    llm = ControlledLLM()

    def missing(_: str) -> ReadingPromptSet:
        raise ReadingPromptNotFoundError("safe")

    service = _service(store, llm, prompt_loader=missing)
    result = await service.generate_preview(store.reading_id, store.user_id, _symbols())

    assert result.failure_code == "prompt_not_found"
    assert not llm.requests and store.failure_writes == 1


def test_more_than_one_repair_attempt_is_rejected() -> None:
    with pytest.raises(ValueError, match="at most one repair"):
        _service(MemoryStore(), ControlledLLM(), max_repair_attempts=2)


async def test_duplicate_symbol_positions_fail_before_provider_call() -> None:
    store = MemoryStore()
    llm = ControlledLLM()
    first = _symbols()[0]
    duplicate = (
        first,
        ReadingSymbolContext(
            symbol=ReadingSymbolInput(
                symbol_id="major_07",
                position=first.symbol.position,
                orientation=SymbolOrientation.UPRIGHT,
                catalog_version="tarot-major-v1",
            ),
            display_name="The Chariot",
            interpretation_theme="Direction and agency.",
        ),
    )

    result = await _service(store, llm).generate_preview(
        store.reading_id,
        store.user_id,
        duplicate,
    )

    assert result.failure_code == "invalid_generation_input"
    assert not llm.requests and store.failure_writes == 1


async def test_cancellation_marks_generation_failed_and_propagates() -> None:
    class CancelledLLM:
        async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
            raise asyncio.CancelledError

    store = MemoryStore()
    service = ReadingGenerationService(store, CancelledLLM())

    with pytest.raises(asyncio.CancelledError):
        await service.generate_preview(store.reading_id, store.user_id, _symbols())

    assert store.failure_writes == 1 and store.failure_code == "generation_cancelled"


async def test_private_content_is_absent_from_logs_and_failure_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    store = MemoryStore()
    llm = ControlledLLM(json.dumps({"title": PRIOR_OUTPUT_MARKER}))

    result = await _run(store, llm, max_repair_attempts=0)

    exposed = caplog.text + repr(result.failure_code) + repr(store.failure_code)
    assert SECRET_QUESTION not in exposed
    assert PRIOR_OUTPUT_MARKER not in exposed
