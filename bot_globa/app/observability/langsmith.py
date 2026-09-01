"""Privacy-safe LangSmith tracing for provider-neutral LLM calls.

Only aggregate operational coordinates are exported. Prompts, schemas, message IDs,
participant labels, provider request IDs, model payloads and memory content never enter
the LangSmith request body.
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.observability.settings import ObservabilitySettings
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


class LangSmithLLMTraceSink:
    """Submit completed privacy-safe LLM traces without adding user-visible latency."""

    def __init__(
        self,
        settings: ObservabilitySettings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.langsmith_enabled:
            raise ValueError("LangSmith trace sink requires enabled settings")
        self._endpoint = settings.langsmith_endpoint
        self._project = settings.langsmith_project.strip()
        self._workspace_id = settings.langsmith_workspace_id.strip()
        self._api_key = settings.langsmith_api_key.get_secret_value().strip()
        self._app_env = settings.app_env
        self._max_pending = settings.langsmith_max_pending_traces
        self._client = client or httpx.AsyncClient(timeout=settings.langsmith_trace_timeout_seconds)
        self._owns_client = client is None
        self._pending: set[asyncio.Task[None]] = set()

    def record(
        self,
        request: LLMRequest,
        *,
        started_at: datetime,
        ended_at: datetime,
        completion: LLMCompletion | None = None,
        failure_code: str | None = None,
    ) -> None:
        if len(self._pending) >= self._max_pending:
            logger.warning("langsmith_trace_dropped reason=pending_limit")
            return
        task = asyncio.create_task(
            self._send(
                request,
                started_at=started_at,
                ended_at=ended_at,
                completion=completion,
                failure_code=failure_code,
            )
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def aclose(self) -> None:
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
        if self._owns_client:
            await self._client.aclose()

    async def _send(
        self,
        request: LLMRequest,
        *,
        started_at: datetime,
        ended_at: datetime,
        completion: LLMCompletion | None,
        failure_code: str | None,
    ) -> None:
        run_id = str(uuid4())
        metadata: dict[str, str | int | bool] = {
            "app_env": self._app_env,
            "repair": request.repair,
        }
        if request.telemetry_persona_code is not None:
            metadata["persona_code"] = request.telemetry_persona_code
        if request.telemetry_prompt_version is not None:
            metadata["prompt_version"] = request.telemetry_prompt_version
        if completion is not None:
            metadata["provider"] = completion.provider
            metadata["model"] = completion.model
            metadata["ls_provider"] = completion.provider
            metadata["ls_model_name"] = completion.model
            if completion.input_tokens is not None:
                metadata["input_tokens"] = completion.input_tokens
            if completion.output_tokens is not None:
                metadata["output_tokens"] = completion.output_tokens
            if completion.latency_ms is not None:
                metadata["latency_ms"] = completion.latency_ms
        if failure_code is not None:
            metadata["failure_code"] = failure_code

        create_payload: dict[str, object] = {
            "id": run_id,
            "name": "numa.llm.generate_structured",
            "run_type": "llm",
            "inputs": {"operation": "structured_generation"},
            "start_time": started_at.isoformat(),
            "session_name": self._project,
            "tags": ["numa", "privacy-safe"],
            "extra": {"metadata": metadata},
        }
        finish_payload: dict[str, object] = {"end_time": ended_at.isoformat()}
        if completion is not None:
            usage_metadata: dict[str, int] = {}
            if completion.input_tokens is not None:
                usage_metadata["input_tokens"] = completion.input_tokens
            if completion.output_tokens is not None:
                usage_metadata["output_tokens"] = completion.output_tokens
            if "input_tokens" in usage_metadata and "output_tokens" in usage_metadata:
                usage_metadata["total_tokens"] = (
                    usage_metadata["input_tokens"] + usage_metadata["output_tokens"]
                )
            outputs: dict[str, object] = {"status": "completed"}
            if usage_metadata:
                outputs["usage_metadata"] = usage_metadata
            finish_payload["outputs"] = outputs
        else:
            finish_payload["error"] = failure_code or "llm_call_failed"

        headers = {"content-type": "application/json", "x-api-key": self._api_key}
        if self._workspace_id:
            headers["x-tenant-id"] = self._workspace_id

        try:
            created = await self._client.post(
                f"{self._endpoint}/runs",
                json=create_payload,
                headers=headers,
            )
            created.raise_for_status()
            finished = await self._client.patch(
                f"{self._endpoint}/runs/{run_id}",
                json=finish_payload,
                headers=headers,
            )
            finished.raise_for_status()
        except (httpx.HTTPError, RuntimeError, TypeError, ValueError):
            logger.warning("langsmith_trace_submission_failed")


class LangSmithObservedLLMClient:
    """Trace LLM calls while preserving the existing LLMClient contract."""

    def __init__(self, inner: LLMClient, sink: LangSmithLLMTraceSink) -> None:
        self._inner = inner
        self._sink = sink

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        started_at = datetime.now(UTC)
        try:
            completion = await self._inner.generate_structured(request)
        except asyncio.CancelledError:
            self._sink.record(
                request,
                started_at=started_at,
                ended_at=datetime.now(UTC),
                failure_code="cancelled",
            )
            raise
        except Exception as error:
            self._sink.record(
                request,
                started_at=started_at,
                ended_at=datetime.now(UTC),
                failure_code=_safe_failure_code(error),
            )
            raise
        self._sink.record(
            request,
            started_at=started_at,
            ended_at=datetime.now(UTC),
            completion=completion,
        )
        return completion

    async def aclose(self) -> None:
        try:
            await close_llm_client(self._inner)
        finally:
            await self._sink.aclose()


def wrap_llm_with_langsmith(
    inner: LLMClient,
    settings: ObservabilitySettings,
    *,
    client: httpx.AsyncClient | None = None,
) -> LLMClient:
    """Return the original client unless privacy-safe LangSmith tracing is enabled."""

    if not settings.langsmith_enabled:
        return inner
    return LangSmithObservedLLMClient(inner, LangSmithLLMTraceSink(settings, client))


def _safe_failure_code(error: Exception) -> str:
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
