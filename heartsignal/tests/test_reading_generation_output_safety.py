"""Generation pipeline coverage for unsafe structured output."""

import json
from uuid import UUID, uuid4

from app.domain.reading import ReadingSymbolInput, SymbolOrientation
from app.domain.reading_generation import (
    ReadingGenerationClaim,
    ReadingGenerationClaimStatus,
    ReadingGenerationContext,
    ReadingGenerationFinalizeStatus,
    ReadingSymbolContext,
    StoredReadingResult,
)
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.services.reading_generation import ReadingGenerationService, ReadingGenerationStatus

PRIVATE_OUTPUT_MARKER = "private-unsafe-output-marker"


def _symbol_contexts() -> tuple[ReadingSymbolContext, ...]:
    return (
        ReadingSymbolContext(
            symbol=ReadingSymbolInput(
                symbol_id="major_20",
                position="current_influence",
                orientation=SymbolOrientation.REVERSED,
                catalog_version="tarot-major-v1",
            ),
            display_name="Judgement",
            interpretation_theme="Delayed review and honest assessment.",
        ),
    )


def _payload(*, title: str = "A reflective pause") -> str:
    symbol = _symbol_contexts()[0]
    return json.dumps(
        {
            "title": title,
            "opening": "The spread invites reflection without promising an outcome.",
            "symbols": [
                {
                    "symbol_id": symbol.symbol.symbol_id,
                    "position": symbol.symbol.position,
                    "orientation": symbol.symbol.orientation.value,
                    "interpretation": "Judgement reversed may point to an unfinished review.",
                }
            ],
            "patterns": ["Momentum may be replacing evaluation."],
            "possible_scenarios": [
                {
                    "scenario": "A pause could make the trade-offs easier to compare.",
                    "conditions": ["Write down what is reversible before deciding."],
                }
            ],
            "reflection_questions": ["Which value do you want to protect?"],
            "practical_step": "Compare both options in writing.",
            "uncertainty_note": "The cards cannot guarantee what will happen.",
            "share_card": {
                "headline": "Pause before momentum decides",
                "short_text": "Use the reading as reflection, not certainty.",
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
                question="Should I pause before deciding?",
                context=None,
                engine_version="symbolic-v1",
                prompt_version="tarot-reader-v1",
                schema_version="reading-result-v1",
            ),
        )
        self.complete_writes = 0
        self.failure_writes = 0
        self.failure_code: str | None = None

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
        assert result and symbols
        self.complete_writes += 1
        return ReadingGenerationFinalizeStatus.COMPLETED

    async def fail_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
    ) -> ReadingGenerationFinalizeStatus:
        assert (reading_id, user_id) == (self.reading_id, self.user_id)
        self.failure_writes += 1
        self.failure_code = failure_code
        return ReadingGenerationFinalizeStatus.COMPLETED


class ControlledLLM:
    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.requests: list[LLMRequest] = []

    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        return LLMCompletion(
            payload=self.outputs.pop(0),
            provider="controlled",
            model="oracle-test-model",
            provider_request_id="request-1",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


async def test_unsafe_output_is_repaired_once_without_payload_echo() -> None:
    store = MemoryStore()
    llm = ControlledLLM(
        _payload(title=f"They will definitely return. {PRIVATE_OUTPUT_MARKER}"),
        _payload(),
    )
    service = ReadingGenerationService(store, llm)

    result = await service.generate_preview(
        store.reading_id,
        store.user_id,
        _symbol_contexts(),
    )

    assert result.status is ReadingGenerationStatus.COMPLETED
    assert result.attempt_count == 2 and result.repair_used
    assert store.complete_writes == 1 and store.failure_writes == 0
    assert len(llm.requests) == 2 and llm.requests[1].repair
    assert "output.title:guaranteed_future" in llm.requests[1].user_prompt
    assert PRIVATE_OUTPUT_MARKER not in llm.requests[1].user_prompt


async def test_two_unsafe_outputs_fail_without_persistence() -> None:
    store = MemoryStore()
    llm = ControlledLLM(
        _payload(title="They will definitely return."),
        _payload(title="The result is guaranteed to happen."),
    )
    service = ReadingGenerationService(store, llm)

    result = await service.generate_preview(
        store.reading_id,
        store.user_id,
        _symbol_contexts(),
    )

    assert result.status is ReadingGenerationStatus.FAILED
    assert result.failure_code == "reading_unsafe_output"
    assert result.attempt_count == 2 and result.repair_used
    assert store.complete_writes == 0
    assert store.failure_writes == 1 and store.failure_code == "reading_unsafe_output"


async def test_unsafe_stored_result_is_treated_as_corrupted_without_llm_call() -> None:
    symbols = tuple(context.symbol for context in _symbol_contexts())
    claim = ReadingGenerationClaim(
        ReadingGenerationClaimStatus.READY,
        ready=StoredReadingResult(
            json.loads(_payload(title="They will definitely return.")),
            symbols,
        ),
    )
    store = MemoryStore(claim)
    llm = ControlledLLM()
    service = ReadingGenerationService(store, llm)

    result = await service.generate_preview(
        store.reading_id,
        store.user_id,
        _symbol_contexts(),
    )

    assert result.status is ReadingGenerationStatus.CORRUPTED_RESULT
    assert not llm.requests
    assert store.complete_writes == 0 and store.failure_writes == 0
