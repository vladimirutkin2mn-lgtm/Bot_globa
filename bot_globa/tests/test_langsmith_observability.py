"""Privacy and failure-isolation coverage for LangSmith LLM tracing."""

import json

import httpx
import pytest
from pydantic import SecretStr

from app.observability.langsmith import wrap_llm_with_langsmith
from app.observability.settings import ObservabilitySettings
from app.providers.llm.base import (
    LLMClient,
    LLMCompletion,
    LLMRequest,
    LLMTimeoutError,
    close_llm_client,
)


class SuccessfulLLM:
    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        del request
        return LLMCompletion(
            payload='{"private":"model output"}',
            provider="openai",
            model="gpt-test",
            provider_request_id="provider-secret-request-id",
            input_tokens=123,
            output_tokens=45,
            latency_ms=678,
        )


class TimeoutLLM:
    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        del request
        raise LLMTimeoutError("sensitive provider exception text")


def _settings() -> ObservabilitySettings:
    return ObservabilitySettings(
        app_env="test",
        langsmith_enabled=True,
        langsmith_api_key=SecretStr("langsmith-test-secret"),
        langsmith_endpoint="https://langsmith.example",
        langsmith_project="numa-test",
        langsmith_workspace_id="workspace-test",
    )


def _private_request() -> LLMRequest:
    return LLMRequest(
        system_prompt="SECRET SYSTEM PROMPT",
        user_prompt="Очень личный вопрос пользователя",
        schema={"private_schema": "SECRET SCHEMA"},
        message_ids=("private-reading-id",),
        participant_labels=("private-person",),
        repair=True,
        telemetry_persona_code="tarot_reader",
        telemetry_prompt_version="tarot-v5",
    )


async def test_langsmith_trace_exports_only_safe_operational_metadata() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    inner: LLMClient = SuccessfulLLM()
    client = wrap_llm_with_langsmith(inner, _settings(), client=http)

    completion = await client.generate_structured(_private_request())
    await close_llm_client(client)
    await http.aclose()

    assert completion.payload == '{"private":"model output"}'
    assert [request.method for request in captured] == ["POST", "PATCH"]
    assert captured[0].headers["x-api-key"] == "langsmith-test-secret"
    assert captured[0].headers["x-tenant-id"] == "workspace-test"

    payloads = [json.loads(request.content) for request in captured]
    serialized = json.dumps(payloads, ensure_ascii=False)
    for private_value in (
        "SECRET SYSTEM PROMPT",
        "Очень личный вопрос пользователя",
        "SECRET SCHEMA",
        "private-reading-id",
        "private-person",
        "model output",
        "provider-secret-request-id",
    ):
        assert private_value not in serialized

    created, finished = payloads
    assert created["inputs"] == {"operation": "structured_generation"}
    assert created["session_name"] == "numa-test"
    assert created["tags"] == ["numa", "privacy-safe"]
    assert created["extra"]["metadata"] == {
        "app_env": "test",
        "repair": True,
        "persona_code": "tarot_reader",
        "prompt_version": "tarot-v5",
        "provider": "openai",
        "model": "gpt-test",
        "input_tokens": 123,
        "output_tokens": 45,
        "latency_ms": 678,
    }
    assert finished["outputs"] == {
        "status": "completed",
        "usage_metadata": {
            "input_tokens": 123,
            "output_tokens": 45,
            "total_tokens": 168,
        },
    }


async def test_langsmith_failure_trace_uses_safe_code_and_preserves_exception() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = wrap_llm_with_langsmith(TimeoutLLM(), _settings(), client=http)

    with pytest.raises(LLMTimeoutError):
        await client.generate_structured(_private_request())
    await close_llm_client(client)
    await http.aclose()

    payloads = [json.loads(request.content) for request in captured]
    serialized = json.dumps(payloads, ensure_ascii=False)
    assert "sensitive provider exception text" not in serialized
    assert payloads[0]["extra"]["metadata"]["failure_code"] == "llm_timeout"
    assert payloads[1]["error"] == "llm_timeout"


async def test_langsmith_transport_failure_never_breaks_generation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = wrap_llm_with_langsmith(SuccessfulLLM(), _settings(), client=http)

    completion = await client.generate_structured(_private_request())
    await close_llm_client(client)
    await http.aclose()

    assert completion.model == "gpt-test"


def test_disabled_langsmith_returns_original_llm_client() -> None:
    inner: LLMClient = SuccessfulLLM()
    settings = ObservabilitySettings(langsmith_enabled=False)

    assert wrap_llm_with_langsmith(inner, settings) is inner
