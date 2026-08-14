"""OpenAI adapter contract tests; no network or real key."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import httpx
import openai
import pytest
from openai import AsyncOpenAI

from app.domain.reading_result import ReadingResult
from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
    LLMUnexpectedError,
)
from app.providers.llm.openai import (
    OpenAILLMClient,
    openai_strict_schema,
    schema_constraints,
)

SECRET = "SECRET-PRIVATE-CONTENT"


@dataclass
class FakeResponse:
    output_text: str = "{}"
    model: str = "actual-model"
    usage: object | None = field(
        default_factory=lambda: SimpleNamespace(input_tokens=17, output_tokens=29)
    )
    _request_id: str = "req-123"


class FakeResponses:
    def __init__(self, *results: object) -> None:
        self.results = list(results or (FakeResponse(),))
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeClient:
    def __init__(self, *results: object) -> None:
        self.responses = FakeResponses(*results)


def request() -> LLMRequest:
    return LLMRequest(
        "system " + SECRET,
        "user " + SECRET,
        ReadingResult.model_json_schema(),
        ("reading-1",),
        (),
    )


def adapter(client: FakeClient, attempts: int = 2) -> OpenAILLMClient:
    return OpenAILLMClient(
        "not-a-real-key",
        "configured-model",
        12.5,
        attempts,
        cast("AsyncOpenAI", client),
    )


async def test_request_contract_and_metadata_extraction() -> None:
    client = FakeClient()
    completion = await adapter(client).generate_structured(request())
    call = client.responses.calls[0]
    assert call["model"] == "configured-model"
    system, user = cast("list[dict[str, Any]]", call["input"])
    assert system == {"type": "message", "role": "system", "content": "system " + SECRET}
    assert user["type"] == "message" and user["role"] == "user"
    # The prompt is sent unchanged; the limits strict mode strips from the schema follow it.
    assert user["content"].startswith("user " + SECRET)
    format_ = cast_dict(cast_dict(call["text"])["format"])
    assert format_["type"] == "json_schema" and format_["strict"] is True
    assert format_["name"] == "structured_result"
    assert call["store"] is False and call["timeout"] == 12.5
    assert (completion.model, completion.provider_request_id) == ("actual-model", "req-123")
    assert (completion.input_tokens, completion.output_tokens) == (17, 29)


def cast_dict(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


async def test_missing_usage_is_safe() -> None:
    completion = await adapter(FakeClient(FakeResponse(usage=None))).generate_structured(request())
    assert completion.input_tokens is None and completion.output_tokens is None


def test_provider_schema_removes_unsupported_keywords_recursively() -> None:
    schema = cast_dict(openai_strict_schema(ReadingResult.model_json_schema()))
    forbidden = {
        "default",
        "examples",
        "format",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "title",
    }

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            if value.get("type") == "object" and isinstance(value.get("properties"), dict):
                assert value["required"] == list(value["properties"])
                assert value["additionalProperties"] is False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    assert schema["additionalProperties"] is False and "$defs" in schema


def sdk_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


def response(status: int) -> httpx.Response:
    return httpx.Response(status, request=sdk_request(), json={"error": {"message": "safe"}})


@pytest.mark.parametrize(
    ("sdk_error", "mapped"),
    [
        (openai.APITimeoutError(request=sdk_request()), LLMTimeoutError),
        (openai.RateLimitError("rate", response=response(429), body=None), LLMRateLimitError),
        (
            openai.AuthenticationError("auth", response=response(401), body=None),
            LLMAuthenticationError,
        ),
        (
            openai.PermissionDeniedError("permission", response=response(403), body=None),
            LLMInvalidRequestError,
        ),
        (openai.BadRequestError("bad", response=response(400), body=None), LLMInvalidRequestError),
        (
            openai.NotFoundError("missing", response=response(404), body=None),
            LLMInvalidRequestError,
        ),
    ],
)
async def test_non_retryable_sdk_errors_are_mapped_once(
    sdk_error: Exception, mapped: type[Exception]
) -> None:
    client = FakeClient(sdk_error)
    with pytest.raises(mapped):
        await adapter(client, 3).generate_structured(request())
    assert len(client.responses.calls) == 1


@pytest.mark.parametrize(
    "sdk_error",
    [
        openai.APIConnectionError(request=sdk_request()),
        openai.InternalServerError("server", response=response(500), body=None),
    ],
)
async def test_transient_errors_retry_to_configured_limit(sdk_error: Exception) -> None:
    client = FakeClient(sdk_error, sdk_error, sdk_error)
    with pytest.raises(LLMTransientError):
        await adapter(client, 3).generate_structured(request())
    assert len(client.responses.calls) == 3


async def test_transient_retry_can_succeed() -> None:
    client = FakeClient(openai.APIConnectionError(request=sdk_request()), FakeResponse())
    result = await adapter(client).generate_structured(request())
    assert result.model == "actual-model" and len(client.responses.calls) == 2


async def test_unexpected_sdk_error_is_mapped_without_private_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeClient(openai.OpenAIError(SECRET))
    with pytest.raises(LLMUnexpectedError):
        await adapter(client).generate_structured(request())
    assert SECRET not in caplog.text


def _stripped_keywords(schema: object, found: set[str] | None = None) -> set[str]:
    """Every constraint keyword strict mode forces out of the schema we send."""

    found = set() if found is None else found
    if isinstance(schema, dict):
        found.update(key for key in schema if key in _CONSTRAINT_KEYWORDS)
        for item in schema.values():
            _stripped_keywords(item, found)
    elif isinstance(schema, list):
        for item in schema:
            _stripped_keywords(item, found)
    return found


_CONSTRAINT_KEYWORDS = {
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
}


async def test_every_limit_removed_from_the_schema_is_stated_in_the_request() -> None:
    """The failure that killed every reading in production: rules enforced but never sent.

    Strict structured outputs reject these keywords, so the schema cannot carry them. If
    they are not restated in words the model breaks a limit it was never shown, and the
    answer is discarded for a rule it had no way to satisfy.
    """

    client = FakeClient(FakeResponse())
    outgoing = request()
    assert _stripped_keywords(outgoing.schema), "the schema under test carries no limits"

    await adapter(client).generate_structured(outgoing)

    sent = cast("list[dict[str, Any]]", client.responses.calls[0]["input"])[1]["content"]
    for expected in (
        "patterns: at most 7 item(s)",
        "possible_scenarios: at least 1 item(s), at most 5 item(s)",
        "ReadingScenario.conditions.each item: at least 1 character(s), at most 500 character(s)",
    ):
        assert expected in sent, expected


async def test_the_stated_limits_follow_the_model_rather_than_a_hand_written_list() -> None:
    """A limit added to a Pydantic model has to appear without anyone editing a prompt."""

    described = schema_constraints(ReadingResult.model_json_schema())

    assert any(line == "symbols: at most 12 item(s)" for line in described)
    assert any(line.startswith("ReadingSymbolResult.symbol_id:") for line in described)


async def test_a_schema_without_limits_adds_nothing_to_the_prompt() -> None:
    client = FakeClient(FakeResponse())
    plain = LLMRequest("system", "user", {"type": "object", "properties": {}}, ("r",), ())

    await adapter(client).generate_structured(plain)

    messages = cast("list[dict[str, Any]]", client.responses.calls[0]["input"])
    assert messages[1]["content"] == "user"
