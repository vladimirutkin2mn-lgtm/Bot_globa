"""Privacy-safe operational telemetry for oracle LLM, astrology and generation quality."""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

from app.providers.analytics import ORACLE_QUALITY_EVENT_VERSION, AnalyticsClient
from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMClient,
    LLMCompletion,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
    LLMUnexpectedError,
    close_llm_client,
)

logger = logging.getLogger(__name__)

LLM_ATTEMPT_EVENT: Final = "oracle_llm_attempt_observed"
ASTROLOGY_EVENT: Final = "oracle_astrology_observed"
GENERATION_EVENT: Final = "oracle_generation_observed"


@dataclass(frozen=True, slots=True)
class LLMCostPolicy:
    """Estimate provider cost only for the configured runtime model."""

    model: str
    input_usd_per_million_tokens: float | None = None
    output_usd_per_million_tokens: float | None = None

    def estimate_microusd(self, completion: LLMCompletion) -> int | None:
        if completion.model != self.model:
            return None
        if (
            self.input_usd_per_million_tokens is None
            or self.output_usd_per_million_tokens is None
            or completion.input_tokens is None
            or completion.output_tokens is None
        ):
            return None
        return round(
            completion.input_tokens * self.input_usd_per_million_tokens
            + completion.output_tokens * self.output_usd_per_million_tokens
        )


class OracleQualityObserver:
    """Record aggregate-safe telemetry outside product correctness paths."""

    def __init__(
        self,
        analytics: AnalyticsClient,
        *,
        default_provider: str,
        default_model: str,
        cost_policy: LLMCostPolicy | None = None,
    ) -> None:
        self._analytics = analytics
        self._default_provider = default_provider
        self._default_model = default_model
        self._cost_policy = cost_policy or LLMCostPolicy(default_model)

    async def generate(
        self,
        llm: LLMClient,
        request: LLMRequest,
        *,
        persona_code: str,
        prompt_version: str,
    ) -> LLMCompletion:
        """Measure one actual provider call, including failed calls that still consume latency."""

        observation_id = uuid4()
        started = time.perf_counter_ns()
        try:
            completion = await llm.generate_structured(request)
        except Exception as error:
            await self._track(
                LLM_ATTEMPT_EVENT,
                {
                    "observation_id": str(observation_id),
                    "persona_code": persona_code,
                    "provider": self._default_provider,
                    "model": self._default_model,
                    "prompt_version": prompt_version,
                    "attempt_kind": "repair" if request.repair else "primary",
                    "status_code": _llm_failure_code(error),
                    "latency_ms": str(elapsed_ms(started)),
                    "cost_known": "false",
                },
            )
            raise
        latency_ms = completion.latency_ms or elapsed_ms(started)
        estimated_cost = self._cost_policy.estimate_microusd(completion)
        properties = {
            "observation_id": str(observation_id),
            "persona_code": persona_code,
            "provider": completion.provider,
            "model": completion.model,
            "prompt_version": prompt_version,
            "attempt_kind": "repair" if request.repair else "primary",
            "status_code": "completed",
            "latency_ms": str(latency_ms),
            "cost_known": "true" if estimated_cost is not None else "false",
        }
        if completion.input_tokens is not None:
            properties["input_tokens"] = str(completion.input_tokens)
        if completion.output_tokens is not None:
            properties["output_tokens"] = str(completion.output_tokens)
        if estimated_cost is not None:
            properties["estimated_cost_microusd"] = str(estimated_cost)
        await self._track(LLM_ATTEMPT_EVENT, properties)
        return completion

    async def astrology(
        self,
        *,
        persona_code: str,
        scope_code: str,
        engine_version: str,
        status_code: str,
        latency_ms: int,
        failure_code: str | None = None,
    ) -> None:
        properties = {
            "observation_id": str(uuid4()),
            "persona_code": persona_code,
            "scope_code": scope_code,
            "engine_version": engine_version,
            "status_code": status_code,
            "latency_ms": str(latency_ms),
        }
        if failure_code is not None:
            properties["failure_code"] = failure_code
        await self._track(ASTROLOGY_EVENT, properties)

    async def generation(
        self,
        *,
        persona_code: str,
        prompt_version: str,
        status_code: str,
        attempt_count: int,
        repair_used: bool,
        failure_code: str | None = None,
    ) -> None:
        properties = {
            "observation_id": str(uuid4()),
            "persona_code": persona_code,
            "prompt_version": prompt_version,
            "status_code": status_code,
            "attempt_count": str(attempt_count),
            "repair_used": "true" if repair_used else "false",
        }
        if failure_code is not None:
            properties["failure_code"] = failure_code
        await self._track(GENERATION_EVENT, properties)

    async def _track(self, event: str, properties: Mapping[str, str]) -> None:
        safe = {"event_version": ORACLE_QUALITY_EVENT_VERSION, **dict(properties)}
        try:
            await self._analytics.track(None, event, safe)
        except Exception:
            logger.warning("oracle_quality_observability_failed event=%s", event)


class ObservedLLMClient:
    """Observe only requests explicitly tagged with aggregate-safe oracle coordinates."""

    def __init__(self, inner: LLMClient, observer: OracleQualityObserver) -> None:
        self._inner = inner
        self._observer = observer

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        persona_code = request.telemetry_persona_code
        prompt_version = request.telemetry_prompt_version
        if persona_code is None or prompt_version is None:
            return await self._inner.generate_structured(request)
        return await self._observer.generate(
            self._inner,
            request,
            persona_code=persona_code,
            prompt_version=prompt_version,
        )

    async def aclose(self) -> None:
        await close_llm_client(self._inner)


def elapsed_ms(started_ns: int) -> int:
    return max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000))


def _llm_failure_code(error: Exception) -> str:
    if isinstance(error, LLMTimeoutError):
        return "llm_timeout"
    if isinstance(error, LLMRateLimitError):
        return "llm_rate_limited"
    if isinstance(error, LLMAuthenticationError):
        return "llm_authentication_error"
    if isinstance(error, LLMInvalidRequestError):
        return "llm_invalid_request"
    if isinstance(error, LLMTransientError):
        return "llm_transient_error"
    if isinstance(error, LLMUnexpectedError):
        return "unexpected_provider_error"
    return "unexpected_pipeline_error"
