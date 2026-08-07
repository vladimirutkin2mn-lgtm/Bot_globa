"""Aggregate-only administration metrics with no user-content fields."""

from collections import Counter, defaultdict
from collections.abc import Iterable

from pydantic import BaseModel
from sqlalchemy import case, func, select
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
            rejection_rows = (
                await session.execute(
                    select(
                        AnalyticsEvent.properties["rejection_reason"].astext,
                        func.count(),
                    )
                    .where(AnalyticsEvent.event_name.in_(_USER_VALIDATION_EVENTS))
                    .group_by(AnalyticsEvent.properties["rejection_reason"].astext)
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
        technical_total = failed + sum(
            count for status, count in jobs.items() if status == "manual_review"
        )
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
    rows: Iterable[tuple[str, dict[str, object]]],
    jobs: dict[str, int],
    outbox: dict[str, int],
) -> OracleQualityMetrics:
    llm: dict[tuple[str, str, str, str], dict[str, object]] = {}
    astrology: dict[tuple[str, str], dict[str, object]] = {}
    generation: dict[tuple[str, str], dict[str, object]] = {}
    input_classified = 0
    output_rejected = 0
    actions: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    payment_failed = 0

    for event_name, raw_properties in rows:
        properties = {str(key): str(value) for key, value in raw_properties.items()}
        if event_name == LLM_ATTEMPT_EVENT:
            key = (
                properties.get("provider", "unknown"),
                properties.get("model", "unknown"),
                properties.get("persona_code", "unknown"),
                properties.get("prompt_version", "unknown"),
            )
            bucket = llm.setdefault(
                key,
                {
                    "calls": 0,
                    "failed": 0,
                    "repairs": 0,
                    "latency_total": 0,
                    "latency_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0,
                    "cost_known": 0,
                },
            )
            bucket["calls"] = int(bucket["calls"]) + 1
            if properties.get("status_code") != "completed":
                bucket["failed"] = int(bucket["failed"]) + 1
            if properties.get("attempt_kind") == "repair":
                bucket["repairs"] = int(bucket["repairs"]) + 1
            _sum_optional_int(bucket, "latency", properties.get("latency_ms"))
            bucket["input_tokens"] = int(bucket["input_tokens"]) + _int(
                properties.get("input_tokens")
            )
            bucket["output_tokens"] = int(bucket["output_tokens"]) + _int(
                properties.get("output_tokens")
            )
            if properties.get("cost_known") == "true":
                bucket["cost_known"] = int(bucket["cost_known"]) + 1
                bucket["cost"] = int(bucket["cost"]) + _int(
                    properties.get("estimated_cost_microusd")
                )
        elif event_name == ASTROLOGY_EVENT:
            key = (
                properties.get("engine_version", "unknown"),
                properties.get("scope_code", "unknown"),
            )
            bucket = astrology.setdefault(
                key,
                {
                    "count": 0,
                    "failed": 0,
                    "latency_total": 0,
                    "latency_count": 0,
                    "failures": Counter(),
                },
            )
            bucket["count"] = int(bucket["count"]) + 1
            if properties.get("status_code") != "completed":
                bucket["failed"] = int(bucket["failed"]) + 1
            _sum_optional_int(bucket, "latency", properties.get("latency_ms"))
            failure_code = properties.get("failure_code")
            if failure_code:
                failures = bucket["failures"]
                assert isinstance(failures, Counter)
                failures[failure_code] += 1
        elif event_name == GENERATION_EVENT:
            key = (
                properties.get("persona_code", "unknown"),
                properties.get("prompt_version", "unknown"),
            )
            bucket = generation.setdefault(
                key,
                {
                    "completed": 0,
                    "failed": 0,
                    "repairs": 0,
                    "attempts_total": 0,
                    "count": 0,
                    "failures": Counter(),
                },
            )
            bucket["count"] = int(bucket["count"]) + 1
            bucket["attempts_total"] = int(bucket["attempts_total"]) + _int(
                properties.get("attempt_count")
            )
            status = properties.get("status_code")
            if status == "completed":
                bucket["completed"] = int(bucket["completed"]) + 1
            else:
                bucket["failed"] = int(bucket["failed"]) + 1
            if properties.get("repair_used") == "true":
                bucket["repairs"] = int(bucket["repairs"]) + 1
            failure_code = properties.get("failure_code")
            if failure_code:
                failures = bucket["failures"]
                assert isinstance(failures, Counter)
                failures[failure_code] += 1
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
                call_count=int(bucket["calls"]),
                failed_call_count=int(bucket["failed"]),
                repair_call_count=int(bucket["repairs"]),
                average_latency_ms=_average(bucket, "latency"),
                input_tokens_total=int(bucket["input_tokens"]),
                output_tokens_total=int(bucket["output_tokens"]),
                estimated_cost_microusd_total=int(bucket["cost"]),
                cost_known_call_count=int(bucket["cost_known"]),
            )
            for (provider, model, persona, prompt), bucket in sorted(llm.items())
        ],
        astrology=[
            OracleAstrologyBucket(
                engine_version=engine,
                scope_code=scope,
                calculation_count=int(bucket["count"]),
                failed_count=int(bucket["failed"]),
                average_latency_ms=_average(bucket, "latency"),
                failure_codes=dict(sorted(_counter(bucket, "failures").items())),
            )
            for (engine, scope), bucket in sorted(astrology.items())
        ],
        generation=[
            OracleGenerationBucket(
                persona_code=persona,
                prompt_version=prompt,
                completed_count=int(bucket["completed"]),
                failed_count=int(bucket["failed"]),
                repair_used_count=int(bucket["repairs"]),
                average_attempt_count=(
                    int(bucket["attempts_total"]) / int(bucket["count"])
                    if int(bucket["count"])
                    else None
                ),
                failure_codes=dict(sorted(_counter(bucket, "failures").items())),
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


def _sum_optional_int(bucket: dict[str, object], prefix: str, value: str | None) -> None:
    if value is None:
        return
    parsed = _int(value)
    bucket[f"{prefix}_total"] = int(bucket[f"{prefix}_total"]) + parsed
    bucket[f"{prefix}_count"] = int(bucket[f"{prefix}_count"]) + 1


def _average(bucket: dict[str, object], prefix: str) -> float | None:
    count = int(bucket[f"{prefix}_count"])
    return int(bucket[f"{prefix}_total"]) / count if count else None


def _counter(bucket: dict[str, object], key: str) -> Counter[str]:
    value = bucket[key]
    assert isinstance(value, Counter)
    return value


def _int(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)
