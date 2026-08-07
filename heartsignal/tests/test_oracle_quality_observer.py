"""Unit contracts for oracle LLM cost, latency and privacy-safe observation."""

from collections.abc import Mapping

import pytest

from app.observability.oracle_quality import (
    LLM_ATTEMPT_EVENT,
    LLMCostPolicy,
    ObservedLLMClient,
    OracleQualityObserver,
)
from app.providers.analytics import ORACLE_QUALITY_EVENT_VERSION, validate_event_properties
from app.providers.llm.base import LLMCompletion, LLMRequest, LLMTimeoutError


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        safe = validate_event_properties(event, properties)
        self.calls.append((user_id, event, safe))


class SuccessfulLLM:
    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        return LLMCompletion(
            payload='{"private":"RESULT-MUST-NOT-ENTER-TELEMETRY"}',
            provider="openai",
            model="quality-model",
            input_tokens=100,
            output_tokens=50,
            latency_ms=321,
        )


class TimeoutLLM:
    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        raise LLMTimeoutError("PRIVATE-PROVIDER-DETAIL")


def _request(*, repair: bool = False, tagged: bool = True) -> LLMRequest:
    return LLMRequest(
        system_prompt="PRIVATE-SYSTEM-PROMPT",
        user_prompt="PRIVATE-USER-PROMPT",
        schema={"type": "object"},
        message_ids=("private-message-id",),
        participant_labels=("private-participant",),
        repair=repair,
        telemetry_persona_code="tarot_reader" if tagged else None,
        telemetry_prompt_version="tarot-reader-v2" if tagged else None,
    )


async def test_observed_llm_records_tokens_latency_cost_and_repair_without_content() -> None:
    recording = RecordingAnalytics()
    observer = OracleQualityObserver(
        recording,
        default_provider="openai",
        default_model="quality-model",
        cost_policy=LLMCostPolicy(
            "quality-model",
            input_usd_per_million_tokens=2.0,
            output_usd_per_million_tokens=6.0,
        ),
    )
    client = ObservedLLMClient(SuccessfulLLM(), observer)

    primary = await client.generate_analysis(_request())
    repair = await client.generate_analysis(_request(repair=True))

    assert primary.payload == repair.payload
    assert len(recording.calls) == 2
    first = recording.calls[0]
    assert first[0] is None
    assert first[1] == LLM_ATTEMPT_EVENT
    assert first[2] == {
        "event_version": ORACLE_QUALITY_EVENT_VERSION,
        "observation_id": first[2]["observation_id"],
        "persona_code": "tarot_reader",
        "provider": "openai",
        "model": "quality-model",
        "prompt_version": "tarot-reader-v2",
        "attempt_kind": "primary",
        "status_code": "completed",
        "latency_ms": "321",
        "cost_known": "true",
        "input_tokens": "100",
        "output_tokens": "50",
        "estimated_cost_microusd": "500",
    }
    assert recording.calls[1][2]["attempt_kind"] == "repair"
    serialized = str(recording.calls)
    for private_value in (
        "PRIVATE-SYSTEM-PROMPT",
        "PRIVATE-USER-PROMPT",
        "RESULT-MUST-NOT-ENTER-TELEMETRY",
        "private-message-id",
        "private-participant",
    ):
        assert private_value not in serialized


async def test_observed_llm_records_safe_failure_code_without_provider_error_text() -> None:
    recording = RecordingAnalytics()
    client = ObservedLLMClient(
        TimeoutLLM(),
        OracleQualityObserver(
            recording,
            default_provider="openai",
            default_model="quality-model",
        ),
    )

    with pytest.raises(LLMTimeoutError):
        await client.generate_analysis(_request())

    assert len(recording.calls) == 1
    properties = recording.calls[0][2]
    assert properties["status_code"] == "llm_timeout"
    assert properties["cost_known"] == "false"
    assert int(properties["latency_ms"]) >= 0
    assert "PRIVATE-PROVIDER-DETAIL" not in str(recording.calls)


async def test_untagged_legacy_llm_request_is_transparent_and_unobserved() -> None:
    recording = RecordingAnalytics()
    client = ObservedLLMClient(
        SuccessfulLLM(),
        OracleQualityObserver(
            recording,
            default_provider="openai",
            default_model="quality-model",
        ),
    )

    completion = await client.generate_analysis(_request(tagged=False))

    assert completion.model == "quality-model"
    assert recording.calls == []
