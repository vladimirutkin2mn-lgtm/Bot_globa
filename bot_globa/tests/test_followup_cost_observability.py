"""Included paid-session follow-ups must be present in privacy-safe LLM cost telemetry."""

from collections.abc import Mapping

from app.observability.oracle_quality import (
    LLM_ATTEMPT_EVENT,
    LLMCostPolicy,
    ObservedLLMClient,
    OracleQualityObserver,
)
from app.providers.analytics import validate_event_properties
from app.providers.llm.base import LLMCompletion, LLMRequest


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.calls.append((user_id, event, validate_event_properties(event, properties)))


class FollowupLLM:
    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        return LLMCompletion(
            payload='{"answer":"PRIVATE-FOLLOWUP-ANSWER"}',
            provider="openai",
            model="quality-model",
            input_tokens=120,
            output_tokens=30,
            latency_ms=50,
        )


def _followup_request(*, repair: bool = False) -> LLMRequest:
    return LLMRequest(
        system_prompt="PRIVATE-SYSTEM",
        user_prompt="PRIVATE-FOLLOWUP-QUESTION",
        schema={"type": "object"},
        message_ids=("private-reading-id",),
        participant_labels=(),
        repair=repair,
        telemetry_prompt_version="reading_followup_v1",
    )


async def test_followups_are_cost_observed_without_private_content_or_ids() -> None:
    recording = RecordingAnalytics()
    client = ObservedLLMClient(
        FollowupLLM(),
        OracleQualityObserver(
            recording,
            default_provider="openai",
            default_model="quality-model",
            cost_policy=LLMCostPolicy(
                "quality-model",
                input_usd_per_million_tokens=2.0,
                output_usd_per_million_tokens=6.0,
            ),
        ),
    )

    await client.generate_structured(_followup_request())
    await client.generate_structured(_followup_request(repair=True))

    assert len(recording.calls) == 2
    primary = recording.calls[0]
    repair = recording.calls[1]
    assert primary[0] is None
    assert primary[1] == LLM_ATTEMPT_EVENT
    assert primary[2]["persona_code"] == "reading_followup"
    assert primary[2]["prompt_version"] == "reading_followup_v1"
    assert primary[2]["attempt_kind"] == "primary"
    assert primary[2]["input_tokens"] == "120"
    assert primary[2]["output_tokens"] == "30"
    assert primary[2]["estimated_cost_microusd"] == "420"
    assert repair[2]["persona_code"] == "reading_followup"
    assert repair[2]["attempt_kind"] == "repair"

    serialized = str(recording.calls)
    for private_value in (
        "PRIVATE-SYSTEM",
        "PRIVATE-FOLLOWUP-QUESTION",
        "PRIVATE-FOLLOWUP-ANSWER",
        "private-reading-id",
    ):
        assert private_value not in serialized


async def test_other_partially_tagged_requests_remain_transparent() -> None:
    recording = RecordingAnalytics()
    client = ObservedLLMClient(
        FollowupLLM(),
        OracleQualityObserver(
            recording,
            default_provider="openai",
            default_model="quality-model",
        ),
    )
    request = LLMRequest(
        system_prompt="PRIVATE-SYSTEM",
        user_prompt="PRIVATE-QUESTION",
        schema={"type": "object"},
        message_ids=(),
        participant_labels=(),
        telemetry_prompt_version="some_other_prompt_v1",
    )

    await client.generate_structured(request)

    assert recording.calls == []
