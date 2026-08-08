"""Deterministic Oracle stub provider tests."""

import json

import pytest
from pydantic import ValidationError

from app.domain.reading_result import ReadingResult
from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
)
from app.providers.llm.stub import StubLLMClient


def llm_request(repair: bool = False) -> LLMRequest:
    input_payload = {
        "persona_code": "tarot_reader",
        "topic": "decision",
        "user_question": "What should I reflect on?",
        "optional_context": None,
        "selected_symbols": [
            {
                "symbol_id": "major_07",
                "position": "current_influence",
                "orientation": "upright",
                "catalog_version": "tarot-major-v1",
                "display_name": "The Chariot",
                "interpretation_theme": "direction",
            }
        ],
    }
    prompt = "Return structured output.\n\nINPUT_JSON:\n" + json.dumps(input_payload)
    if repair:
        prompt += "\n\nCORRECTION_INSTRUCTION:\nReturn a valid payload."
    return LLMRequest(
        "system",
        prompt,
        ReadingResult.model_json_schema(),
        ("reading-1",),
        (),
        repair,
    )


async def test_default_stub_returns_oracle_reading_result() -> None:
    client = StubLLMClient()
    completion = await client.generate_structured(llm_request())
    result = ReadingResult.model_validate_json(completion.payload)
    assert completion.provider == "stub"
    assert result.symbols[0].symbol_id == "major_07"
    assert result.symbols[0].position == "current_influence"
    assert result.symbols[0].orientation.value == "upright"


@pytest.mark.parametrize("behavior", ["invalid_json", "invalid_schema"])
async def test_invalid_stub_payload_behaviors(behavior: str) -> None:
    client = StubLLMClient(behavior=behavior)  # type: ignore[arg-type]
    completion = await client.generate_structured(llm_request())
    with pytest.raises((ValueError, ValidationError)):
        ReadingResult.model_validate_json(completion.payload)


async def test_invalid_semantics_remains_schema_valid_but_changes_symbol_identity() -> None:
    completion = await StubLLMClient(behavior="invalid_semantics").generate_structured(
        llm_request()
    )
    result = ReadingResult.model_validate_json(completion.payload)
    assert result.symbols[0].symbol_id == "unexpected_symbol"


@pytest.mark.parametrize(
    ("behavior", "error"),
    [
        ("timeout", LLMTimeoutError),
        ("rate_limit", LLMRateLimitError),
        ("authentication_error", LLMAuthenticationError),
        ("transport_error", LLMTransientError),
    ],
)
async def test_stub_error_behaviors(behavior: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        await StubLLMClient(behavior=behavior).generate_structured(  # type: ignore[arg-type]
            llm_request()
        )


async def test_stub_repair_success_and_failure() -> None:
    success = StubLLMClient(behavior="repair_success")
    first = await success.generate_structured(llm_request())
    with pytest.raises(ValidationError):
        ReadingResult.model_validate_json(first.payload)
    repaired = await success.generate_structured(llm_request(True))
    ReadingResult.model_validate_json(repaired.payload)

    failure = StubLLMClient(behavior="repair_failure")
    with pytest.raises(ValidationError):
        ReadingResult.model_validate_json(
            (await failure.generate_structured(llm_request(True))).payload
        )
