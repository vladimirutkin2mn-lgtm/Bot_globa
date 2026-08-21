"""Generation product events contain counts and versions, never prompt or memory text."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryKind,
    MemorySourceType,
)
from app.domain.reading import ReadingSymbolInput, SymbolOrientation
from app.domain.reading_generation import (
    ReadingGenerationClaim,
    ReadingGenerationClaimStatus,
    ReadingGenerationContext,
    ReadingGenerationFinalizeStatus,
    ReadingSymbolContext,
)
from app.domain.reading_memory_context import ReadingMemoryContextItem
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.reading_generation import (
    ReadingGenerationService,
    ReadingGenerationStatus,
)


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.calls.append((user_id, event, dict(properties or {})))


class ClaimedStore:
    def __init__(self, reading_id: UUID, user_id: UUID) -> None:
        self.claim = ReadingGenerationClaim(
            ReadingGenerationClaimStatus.CLAIMED,
            context=ReadingGenerationContext(
                reading_id=reading_id,
                user_id=user_id,
                persona_code="tarot_reader",
                topic="decision",
                question="PRIVATE-GENERATION-QUESTION",
                context="PRIVATE-GENERATION-CONTEXT",
                engine_version="symbolic-v1",
                prompt_version="tarot-reader-v4",
                schema_version="reading-result-v1",
            ),
        )
        self.completed: dict[str, object] | None = None

    async def claim_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> ReadingGenerationClaim:
        return self.claim

    async def complete_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: tuple[ReadingSymbolInput, ...],
    ) -> ReadingGenerationFinalizeStatus:
        self.completed = result
        return ReadingGenerationFinalizeStatus.COMPLETED

    async def fail_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
    ) -> ReadingGenerationFinalizeStatus:
        raise AssertionError((reading_id, user_id, failure_code))


class ValidLLM:
    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        return LLMCompletion(
            payload=json.dumps(
                {
                    "title": "A reflective title",
                    "opening": "The symbol suggests a pause before choosing.",
                    "symbols": [
                        {
                            "symbol_id": "major-00-fool",
                            "position": "situation",
                            "orientation": "upright",
                            "interpretation": ("A new route is possible, with uncertainty."),
                        }
                    ],
                    "patterns": ["A choice may benefit from a reversible first step."],
                    "possible_scenarios": [
                        {
                            "scenario": "A small experiment clarifies the direction.",
                            "conditions": ["Keep the first step reversible."],
                        }
                    ],
                    "reflection_questions": ["What evidence supports the change?"],
                    "practical_step": "Write down one reversible experiment.",
                    "uncertainty_note": "This reading cannot predict the future.",
                    "share_card": {
                        "headline": "A possible new route",
                        "short_text": ("Pause, observe, and choose one low-risk experiment."),
                    },
                    "safety": {"high_risk_detected": False, "categories": []},
                }
            ),
            provider="test",
            model="analytics-test",
        )


class TwoMemories:
    async def retrieve(
        self,
        user_id: UUID,
        *,
        persona_code: str,
        topic: str,
        question: str,
        context: str | None,
    ) -> tuple[ReadingMemoryContextItem, ...]:
        now = datetime.now(UTC)
        return (
            ReadingMemoryContextItem(
                kind=MemoryKind.PERSONAL_GOAL,
                claim_basis=MemoryClaimBasis.USER_STATED,
                source_type=MemorySourceType.USER_EXPLICIT,
                value="PRIVATE-USER-STATED-MEMORY",
                confidence_milli=900,
                created_at=now,
                source_reading_created_at=None,
            ),
            ReadingMemoryContextItem(
                kind=MemoryKind.RECURRING_THEME,
                claim_basis=MemoryClaimBasis.MODEL_INFERRED,
                source_type=MemorySourceType.READING_DERIVED,
                value="PRIVATE-MODEL-INFERRED-MEMORY",
                confidence_milli=700,
                created_at=now,
                source_reading_created_at=None,
            ),
        )


async def test_generation_events_contain_only_safe_counts_and_versions() -> None:
    reading_id, user_id = uuid4(), uuid4()
    recording = RecordingAnalytics()
    symbol = ReadingSymbolInput(
        symbol_id="major-00-fool",
        position="situation",
        orientation=SymbolOrientation.UPRIGHT,
        catalog_version="tarot-rws-v1",
    )
    outcome = await ReadingGenerationService(
        ClaimedStore(reading_id, user_id),
        ValidLLM(),
        memory_retriever=TwoMemories(),
        analytics=OracleProductAnalytics(recording),
    ).generate_preview(
        reading_id,
        user_id,
        (
            ReadingSymbolContext(
                symbol=symbol,
                display_name="The Fool",
                interpretation_theme="A reversible beginning",
            ),
        ),
    )

    assert outcome.status is ReadingGenerationStatus.COMPLETED
    assert [event for _, event, _ in recording.calls] == [
        "reading_preview_ready",
        "memory_context_used",
    ]
    preview = recording.calls[0][2]
    memory = recording.calls[1][2]
    assert preview["reading_id"] == str(reading_id)
    assert preview["memory_count"] == "2"
    assert memory["selected_count"] == "2"
    assert memory["user_stated_count"] == "1"
    assert memory["model_inferred_count"] == "1"
    serialized = str(recording.calls)
    for private_value in (
        "PRIVATE-GENERATION-QUESTION",
        "PRIVATE-GENERATION-CONTEXT",
        "PRIVATE-USER-STATED-MEMORY",
        "PRIVATE-MODEL-INFERRED-MEMORY",
        "A reflective title",
        "A new route is possible",
    ):
        assert private_value not in serialized
