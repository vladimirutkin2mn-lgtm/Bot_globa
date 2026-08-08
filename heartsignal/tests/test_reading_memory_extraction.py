"""Unit coverage for topic-neutral completed-reading memory extraction."""

import json
from uuid import uuid4

import pytest

from app.domain.memory_extraction import CompletedReadingMemorySnapshot
from app.domain.oracle_memory import MemoryClaimBasis, MemoryKind
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.services.reading_memory_extraction import (
    InvalidMemoryExtractionError,
    LLMReadingMemoryExtractor,
)


class FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.requests: list[LLMRequest] = []

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        return LLMCompletion(
            payload=self.payload,
            provider="fake",
            model="fake-memory",
        )


def _snapshot() -> CompletedReadingMemorySnapshot:
    return CompletedReadingMemorySnapshot(
        reading_id=uuid4(),
        persona_code="tarot_reader",
        topic="life",
        question="Help me reflect on several difficult circumstances",
        context=None,
        result={"title": "Reflection"},
    )


async def test_llm_extractor_does_not_filter_high_stakes_topics() -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "kind": "user_statement",
                    "value": "User reported a medical diagnosis",
                    "confidence_milli": 1000,
                    "claim_basis": "user_stated",
                },
                {
                    "kind": "user_statement",
                    "value": "User is involved in a legal dispute",
                    "confidence_milli": 1000,
                    "claim_basis": "user_stated",
                },
                {
                    "kind": "personal_goal",
                    "value": "User wants to get out of debt",
                    "confidence_milli": 950,
                    "claim_basis": "user_stated",
                },
                {
                    "kind": "user_statement",
                    "value": "User reported crisis thoughts",
                    "confidence_milli": 1000,
                    "claim_basis": "user_stated",
                },
                {
                    "kind": "recurring_theme",
                    "value": "The reading inferred a recurring theme of control",
                    "confidence_milli": 650,
                    "claim_basis": "model_inferred",
                },
            ]
        },
        ensure_ascii=False,
    )
    llm = FakeLLM(payload)
    extractor = LLMReadingMemoryExtractor(llm)

    result = await extractor.extract(_snapshot())

    assert len(result.candidates) == 5
    assert [candidate.kind for candidate in result.candidates[:4]] == [
        MemoryKind.USER_STATEMENT,
        MemoryKind.USER_STATEMENT,
        MemoryKind.PERSONAL_GOAL,
        MemoryKind.USER_STATEMENT,
    ]
    assert result.candidates[-1].claim_basis is MemoryClaimBasis.MODEL_INFERRED
    assert "Do not suppress a candidate solely because" in llm.requests[0].system_prompt
    assert "untrusted data" in llm.requests[0].system_prompt


async def test_llm_extractor_rejects_unstructured_payload_without_leaking_text() -> None:
    secret = "sensitive private text"
    extractor = LLMReadingMemoryExtractor(FakeLLM(secret))

    with pytest.raises(InvalidMemoryExtractionError) as error:
        await extractor.extract(_snapshot())

    assert secret not in str(error.value)
