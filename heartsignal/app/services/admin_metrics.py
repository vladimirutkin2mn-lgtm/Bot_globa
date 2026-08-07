"""Aggregate-only administration metrics with no user-content fields."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.db.models import (
    Analysis,
    BillingJob,
    BillingOutboxEvent,
    CreditTransaction,
)
from app.observability.oracle_quality import (
    ASTROLOGY_EVENT,
    GENERATION_EVENT,
    LLM_ATTEMPT_EVENT,
)
from app.providers.analytics import OracleProductEvent

_USER_VALIDATION_EVENTS = frozenset({"conversation_rejected"})
_QUALITY_EVENTS = frozenset({LLM_ATTEMPT_EVENT, ASTROLOGY_EVENT, GENERATION_EVENT})
_SAFETY_EVENTS = frozenset(
    {
        OracleProductEvent.SAFETY_INPUT_CLASSIFIED.value,
        OracleProductEvent.SAFETY_OUTPUT_REJECTED.value,
    }
)
_BILLING_EVENTS = frozenset({"payment_failed"})


class ModelUsageMetrics(BaseModel):
    average_latency_ms: float | None
    average_input_tokens: float | None
    average_output_tokens: float | None
    average_total_tokens: float | None
    average_cost_units: float | None


class PurchaseMetrics(BaseModel):
    transaction_count: int
    purchased_credit_total: int


class FailureMetrics(BaseModel):
    user_validation_total: int
    technical_total: int
    conversation_rejection_reasons: dict[str, int]
    analysis_failure_codes: dict[str, int]


class OracleLLMUsageBucket(BaseModel):
    provider: str
    model: str
    persona_code: str
    prompt_version: str
    call_count: int
    failed_call_count: int
    repair_call_count: int
    average_latency_ms: float | None
    input_tokens_total: int
    output_tokens_total: int
    estimated_cost_microusd_total: int
    cost_known_call_count: int


class OracleAstrologyBucket(BaseModel):
    engine_version: str
    scope_code: str
    calculation_count: int
    failed_count: int
    average_latency_ms: float | None
    failure_codes: dict[str, int]


class OracleGenerationBucket(BaseModel):
    persona_code: str
    prompt_version: str
    completed_count: int
    failed_count: int
    repair_used_count: int
    average_attempt_count: float | None
    failure_codes: dict[str, int]


class OracleSafetyHealth(BaseModel):
    input_classified_total: int
    output_rejected_total: int
    action_codes: dict[str, int]
    category_codes: dict[str, int]


class OracleBillingHealth(BaseModel):
    payment_failed_events: int
    jobs_manual_review: int
    jobs_pending_or_claimed: int
    outbox_manual_review: int
    outbox_pending_or_claimed: int


class OracleQualityMetrics(BaseModel):
    llm: list[OracleLLMUsageBucket]
    astrology: list[OracleAstrologyBucket]
    generation: list[OracleGenerationBucket]
    safety: OracleSafetyHealth
    billing: OracleBillingHealth


class AdminMetrics(BaseModel):
    analyses_by_status: dict[str, int]
    terminal_completed: int
    terminal_failed: int
    completion_rate: float | None
    model_usage: ModelUsageMetrics
    purchases: PurchaseMetrics
    funnel_events: dict[str, int]
    failures: FailureMetrics
    billing_jobs_by_status: dict[str, int]
    billing_outbox_by_status: dict[str, int]
    oracle_quality: OracleQualityMetrics


@dataclass(slots=True)
class _LLMAccumulator:
    calls: int = 0
    failed: int = 0
    repairs: int = 0
    latency_total: int = 0
    latency_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: int = 0
    cost_known: int = 0


@dataclass(slots=True)
class _AstrologyAccumulator:
    count: int = 0
    failed: int = 0
    latency_total: int = 0
    latency_count: int = 0
    failures: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class _GenerationAccumulator:
    completed: int = 0
    failed: int = 0
    repairs: int = 0
    attempts_total: int = 0
    count: int = 0
    failures: Counter[str] = field(default_factory=Counter)


class AdminMetricsService:
    """Compute global aggregates; no rows contain prompts or user identities."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def snapshot(self) -> AdminMetrics:
        async with self._sessions() as session:
            status_rows = (
                await session.execute(
                    select(Analysis.status, func.count()).group_by(Analysis.status)
                )
            ).all()
            statuses = {status: int(count) for status, count in status_rows}
            completed = statuses.get("completed", 0)
            failed = statuses.get("failed", 0)
            terminal = completed + failed
            model_row = (
                await session.execute(
                    select(
                        func.avg(Analysis.latency_ms),
                        func.avg(Analysis.input_tokens),
                        func.avg(Analysis.output_tokens),
                        func.avg(
                            func.coalesce(Analysis.input_tokens, 0)
                            + func.coalesce(Analysis.output_tokens, 0)
                        ),
                        func.avg(Analysis.cost_units),
                    ).where(Analysis.status.in_(("completed", "failed")))
                )
            ).one()
            purchase_row = (
                await session.execute(
                    select(
                        func.count(CreditTransaction.id),
                        func.coalesce(func.sum(CreditTransaction.amount), 0),
                    ).where(CreditTransaction.type == "purchase")
                )
            ).one()
            funnel_rows = (
                await session.execute(
                    select(AnalyticsEvent.event_name, func.count()).group_by(
                        AnalyticsEvent.event_name
                    )
                )
            ).all()
            funnel = {event: int(count) for event, count in funnel_rows}
            rejection_reason = AnalyticsEvent.properties["rejection_reason"].astext
            rejection_rows = (
                await session.execute(
                    select(rejection_reason, func.count())
                    .where(AnalyticsEvent.event_name.in_(_USER_VALIDATION_EVENTS))
                    .group_by(rejection_reason)
                )
            ).all()
            analysis_failure_rows = (
                await session.execute(
                    select(Analysis.failure_code, func.count())
                    .where(Analysis.status == "failed", Analysis.failure_code.is_not(None))
                    .group_by(Analysis.failure_code)
                )
            ).all()
            job_rows = (
                await session.execute(
                    select(BillingJob.status, func.count()).group_by(BillingJob.status)
                )
            ).all()
            outbox_rows = (
                await session.execute(
                    select(BillingOutboxEvent.status, func.count()).group_by(
                        BillingOutboxEvent.status
                    )
                )
            ).all()
            quality_rows = list(
                (
                    await session.execute(
                        select(AnalyticsEvent.event_name, AnalyticsEvent.properties).where(
                            AnalyticsEvent.event_name.in_(
                                _QUALITY_EVENTS | _SAFETY_EVENTS | _BILLING_EVENTS
                            )
                        )
                    )
                ).tuples()
            )

        jobs = {status: int(count) for status, count in job_rows}
        outbox = {status: int(count) for status, count in outbox_rows}
        technical_total = failed + jobs.get("manual_review", 0)
        return AdminMetrics(
            analyses_by_status=statuses,
            terminal_completed=completed,
            terminal_failed=failed,
            completion_rate=(completed / terminal) if terminal else None,
            model_usage=ModelUsageMetrics(
                average_latency_ms=_float_or_none(model_row[0]),
                average_input_tokens=_float_or_none(model_row[1]),
                average_output_tokens=_float_or_none(model_row[2]),
                average_total_tokens=_float_or_none(model_row[3]),
                average_cost_units=_float_or_none(model_row[4]),
            ),
            purchases=PurchaseMetrics(
                transaction_count=int(purchase_row[0]),
                purchased_credit_total=int(purchase_row[1]),
            ),
            funnel_events=funnel,
            failures=FailureMetrics(
                user_validation_total=sum(int(count) for _, count in rejection_rows),
                technical_total=technical_total,
                conversation_rejection_reasons={
                    str(reason): int(count)
                    for reason, count in rejection_rows
                    if reason is not None
                },
                analysis_failure_codes={
                    str(code): int(count)
                    for code, count in analysis_failure_rows
                    if code is not None
                },
            ),
            billing_jobs_by_status=jobs,
            billing_outbox_by_status=outbox,
            oracle_quality=_oracle_quality(quality_rows, jobs, outbox),
        )


def _oracle_quality(
    rows: Iterable[tuple[str, Mapping[str, str]]],
    jobs: dict[str, int],
    outbox: dict[str, int],
) -> OracleQualityMetrics:
    llm: dict[tuple[str, str, str, str], _LLMAccumulator] = {}
    astrology: dict[tuple[str, str], _AstrologyAccumulator] = {}
    generation: dict[tuple[str, str], _GenerationAccumulator] = {}
    input_classified = 0
    output_rejected = 0
    actions: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    payment_failed = 0

    for event_name, raw_properties in rows:
        properties = dict(raw_properties)
        if event_name == LLM_ATTEMPT_EVENT:
            llm_key = (
                properties.get("provider", "unknown"),
                properties.get("model", "unknown"),
                properties.get("persona_code", "unknown"),
                properties.get("prompt_version", "unknown"),
            )
            llm_bucket = llm.setdefault(llm_key, _LLMAccumulator())
            llm_bucket.calls += 1
            llm_bucket.failed += properties.get("status_code") != "completed"
            llm_bucket.repairs += properties.get("attempt_kind") == "repair"
            latency = _optional_int(properties.get("latency_ms"))
            if latency is not None:
                llm_bucket.latency_total += latency
                llm_bucket.latency_count += 1
            llm_bucket.input_tokens += _int(properties.get("input_tokens"))
            llm_bucket.output_tokens += _int(properties.get("output_tokens"))
            if properties.get("cost_known") == "true":
                llm_bucket.cost_known += 1
                llm_bucket.cost += _int(properties.get("estimated_cost_microusd"))
        elif event_name == ASTROLOGY_EVENT:
            astrology_key = (
                properties.get("engine_version", "unknown"),
                properties.get("scope_code", "unknown"),
            )
            astrology_bucket = astrology.setdefault(astrology_key, _AstrologyAccumulator())
            astrology_bucket.count += 1
            astrology_bucket.failed += properties.get("status_code") != "completed"
            latency = _optional_int(properties.get("latency_ms"))
            if latency is not None:
                astrology_bucket.latency_total += latency
                astrology_bucket.latency_count += 1
            if failure_code := properties.get("failure_code"):
                astrology_bucket.failures[failure_code] += 1
        elif event_name == GENERATION_EVENT:
            generation_key = (
                properties.get("persona_code", "unknown"),
                properties.get("prompt_version", "unknown"),
            )
            generation_bucket = generation.setdefault(generation_key, _GenerationAccumulator())
            generation_bucket.count += 1
            generation_bucket.attempts_total += _int(properties.get("attempt_count"))
            if properties.get("status_code") == "completed":
                generation_bucket.completed += 1
            else:
                generation_bucket.failed += 1
            generation_bucket.repairs += properties.get("repair_used") == "true"
            if failure_code := properties.get("failure_code"):
                generation_bucket.failures[failure_code] += 1
        elif event_name == OracleProductEvent.SAFETY_INPUT_CLASSIFIED.value:
            input_classified += 1
            if action := properties.get("action_code"):
                actions[action] += 1
            if category := properties.get("category_codes"):
                categories[category] += 1
        elif event_name == OracleProductEvent.SAFETY_OUTPUT_REJECTED.value:
            output_rejected += 1
            if category := properties.get("category_codes"):
                categories[category] += 1
        elif event_name == "payment_failed":
            payment_failed += 1

    return OracleQualityMetrics(
        llm=[
            OracleLLMUsageBucket(
                provider=provider,
                model=model,
                persona_code=persona,
                prompt_version=prompt,
                call_count=bucket.calls,
                failed_call_count=bucket.failed,
                repair_call_count=bucket.repairs,
                average_latency_ms=_average(bucket.latency_total, bucket.latency_count),
                input_tokens_total=bucket.input_tokens,
                output_tokens_total=bucket.output_tokens,
                estimated_cost_microusd_total=bucket.cost,
                cost_known_call_count=bucket.cost_known,
            )
            for (provider, model, persona, prompt), bucket in sorted(llm.items())
        ],
        astrology=[
            OracleAstrologyBucket(
                engine_version=engine,
                scope_code=scope,
                calculation_count=bucket.count,
                failed_count=bucket.failed,
                average_latency_ms=_average(bucket.latency_total, bucket.latency_count),
                failure_codes=dict(sorted(bucket.failures.items())),
            )
            for (engine, scope), bucket in sorted(astrology.items())
        ],
        generation=[
            OracleGenerationBucket(
                persona_code=persona,
                prompt_version=prompt,
                completed_count=bucket.completed,
                failed_count=bucket.failed,
                repair_used_count=bucket.repairs,
                average_attempt_count=(
                    bucket.attempts_total / bucket.count if bucket.count else None
                ),
                failure_codes=dict(sorted(bucket.failures.items())),
            )
            for (persona, prompt), bucket in sorted(generation.items())
        ],
        safety=OracleSafetyHealth(
            input_classified_total=input_classified,
            output_rejected_total=output_rejected,
            action_codes=dict(sorted(actions.items())),
            category_codes=dict(sorted(categories.items())),
        ),
        billing=OracleBillingHealth(
            payment_failed_events=payment_failed,
            jobs_manual_review=jobs.get("manual_review", 0),
            jobs_pending_or_claimed=jobs.get("pending", 0) + jobs.get("claimed", 0),
            outbox_manual_review=outbox.get("manual_review", 0),
            outbox_pending_or_claimed=outbox.get("pending", 0) + outbox.get("claimed", 0),
        ),
    )


def _average(total: int, count: int) -> float | None:
    return total / count if count else None


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _int(value: str | None) -> int:
    return _optional_int(value) or 0


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)
