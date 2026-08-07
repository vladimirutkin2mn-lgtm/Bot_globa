"""PostgreSQL aggregation contracts for oracle cost and quality observability."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.db.models import BillingJob, BillingOutboxEvent
from app.observability.oracle_quality import ASTROLOGY_EVENT, GENERATION_EVENT, LLM_ATTEMPT_EVENT
from app.providers.analytics import ORACLE_QUALITY_EVENT_VERSION, PRODUCT_EVENT_TAXONOMY_VERSION
from app.services.admin_metrics import AdminMetricsService
from tests.payment_postgres_helpers import payment_db  # noqa: F401


def _quality(
    event: str,
    observation_id: str,
    properties: dict[str, str],
) -> AnalyticsEvent:
    return AnalyticsEvent(
        event_name=event,
        subject_id=None,
        properties={
            "event_version": ORACLE_QUALITY_EVENT_VERSION,
            "observation_id": observation_id,
            **properties,
        },
        idempotency_key=f"{event}:{observation_id}",
        correlation_id=f"quality-{observation_id}",
    )


async def test_admin_metrics_group_oracle_cost_quality_safety_and_billing_health(
    payment_db: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    private_sentinel = "PRIVATE-OBSERVABILITY-SENTINEL"
    async with payment_db.begin() as session:
        session.add_all(
            [
                _quality(
                    LLM_ATTEMPT_EVENT,
                    str(uuid4()),
                    {
                        "persona_code": "tarot_reader",
                        "provider": "openai",
                        "model": "quality-model",
                        "prompt_version": "tarot-reader-v2",
                        "attempt_kind": "primary",
                        "status_code": "completed",
                        "latency_ms": "100",
                        "input_tokens": "100",
                        "output_tokens": "50",
                        "estimated_cost_microusd": "500",
                        "cost_known": "true",
                    },
                ),
                _quality(
                    LLM_ATTEMPT_EVENT,
                    str(uuid4()),
                    {
                        "persona_code": "tarot_reader",
                        "provider": "openai",
                        "model": "quality-model",
                        "prompt_version": "tarot-reader-v2",
                        "attempt_kind": "repair",
                        "status_code": "completed",
                        "latency_ms": "300",
                        "input_tokens": "80",
                        "output_tokens": "20",
                        "estimated_cost_microusd": "280",
                        "cost_known": "true",
                    },
                ),
                _quality(
                    LLM_ATTEMPT_EVENT,
                    str(uuid4()),
                    {
                        "persona_code": "love_oracle",
                        "provider": "openai",
                        "model": "quality-model",
                        "prompt_version": "love-oracle-v1",
                        "attempt_kind": "primary",
                        "status_code": "llm_timeout",
                        "latency_ms": "700",
                        "cost_known": "false",
                    },
                ),
                _quality(
                    ASTROLOGY_EVENT,
                    str(uuid4()),
                    {
                        "persona_code": "astrologer",
                        "scope_code": "month_forecast",
                        "engine_version": "astronomy-engine-2.1.19",
                        "status_code": "completed",
                        "latency_ms": "40",
                    },
                ),
                _quality(
                    ASTROLOGY_EVENT,
                    str(uuid4()),
                    {
                        "persona_code": "astrologer",
                        "scope_code": "month_forecast",
                        "engine_version": "astronomy-engine-2.1.19",
                        "status_code": "failed",
                        "latency_ms": "60",
                        "failure_code": "birth_profile_unavailable",
                    },
                ),
                _quality(
                    GENERATION_EVENT,
                    str(uuid4()),
                    {
                        "persona_code": "tarot_reader",
                        "prompt_version": "tarot-reader-v2",
                        "status_code": "completed",
                        "attempt_count": "2",
                        "repair_used": "true",
                    },
                ),
                _quality(
                    GENERATION_EVENT,
                    str(uuid4()),
                    {
                        "persona_code": "tarot_reader",
                        "prompt_version": "tarot-reader-v2",
                        "status_code": "failed",
                        "attempt_count": "1",
                        "repair_used": "false",
                        "failure_code": "reading_invalid_semantics",
                    },
                ),
                AnalyticsEvent(
                    event_name="safety_input_classified",
                    subject_id=str(uuid4()),
                    properties={
                        "event_version": PRODUCT_EVENT_TAXONOMY_VERSION,
                        "persona_code": "love_oracle",
                        "stage_code": "input",
                        "action_code": "handoff",
                        "category_codes": "crisis",
                    },
                    idempotency_key=f"safety_input_classified:{uuid4()}",
                    correlation_id="safety-input",
                ),
                AnalyticsEvent(
                    event_name="safety_output_rejected",
                    subject_id=str(uuid4()),
                    properties={
                        "event_version": PRODUCT_EVENT_TAXONOMY_VERSION,
                        "reading_id": str(uuid4()),
                        "persona_code": "astrologer",
                        "validator_version": "oracle-safety-v1",
                        "category_codes": "financial",
                        "repair_used": "true",
                    },
                    idempotency_key=f"safety_output_rejected:{uuid4()}",
                    correlation_id="safety-output",
                ),
                AnalyticsEvent(
                    event_name="payment_failed",
                    subject_id=str(uuid4()),
                    properties={"failure_code": "provider_declined"},
                    idempotency_key=f"payment_failed:{uuid4()}",
                    correlation_id="billing-failure",
                ),
                BillingJob(
                    job_type="payment_reconciliation",
                    provider="stripe",
                    object_type="payment_order",
                    object_id=str(uuid4()),
                    idempotency_key=f"job:{uuid4()}",
                    status="manual_review",
                ),
                BillingJob(
                    job_type="payment_reconciliation",
                    provider="stripe",
                    object_type="payment_order",
                    object_id=str(uuid4()),
                    idempotency_key=f"job:{uuid4()}",
                    status="pending",
                ),
                BillingOutboxEvent(
                    aggregate_type="payment_order",
                    aggregate_id=str(uuid4()),
                    event_type="purchase_completed",
                    payload={"safe_marker": private_sentinel},
                    idempotency_key=f"outbox:{uuid4()}",
                    status="claimed",
                ),
                BillingOutboxEvent(
                    aggregate_type="payment_order",
                    aggregate_id=str(uuid4()),
                    event_type="payment_failed",
                    payload={},
                    idempotency_key=f"outbox:{uuid4()}",
                    status="manual_review",
                ),
            ]
        )

    metrics = await AdminMetricsService(payment_db).snapshot()

    tarot = next(
        bucket
        for bucket in metrics.oracle_quality.llm
        if bucket.persona_code == "tarot_reader"
    )
    assert tarot.call_count == 2
    assert tarot.failed_call_count == 0
    assert tarot.repair_call_count == 1
    assert tarot.average_latency_ms == 200.0
    assert tarot.input_tokens_total == 180
    assert tarot.output_tokens_total == 70
    assert tarot.estimated_cost_microusd_total == 780
    assert tarot.cost_known_call_count == 2

    love = next(
        bucket
        for bucket in metrics.oracle_quality.llm
        if bucket.persona_code == "love_oracle"
    )
    assert love.failed_call_count == 1
    assert love.cost_known_call_count == 0

    astrology = metrics.oracle_quality.astrology[0]
    assert astrology.calculation_count == 2
    assert astrology.failed_count == 1
    assert astrology.average_latency_ms == 50.0
    assert astrology.failure_codes == {"birth_profile_unavailable": 1}

    generation = metrics.oracle_quality.generation[0]
    assert generation.completed_count == 1
    assert generation.failed_count == 1
    assert generation.repair_used_count == 1
    assert generation.average_attempt_count == 1.5
    assert generation.failure_codes == {"reading_invalid_semantics": 1}

    assert metrics.oracle_quality.safety.input_classified_total == 1
    assert metrics.oracle_quality.safety.output_rejected_total == 1
    assert metrics.oracle_quality.safety.action_codes == {"handoff": 1}
    assert metrics.oracle_quality.safety.category_codes == {"crisis": 1, "financial": 1}
    assert metrics.oracle_quality.billing.payment_failed_events == 1
    assert metrics.oracle_quality.billing.jobs_manual_review == 1
    assert metrics.oracle_quality.billing.jobs_pending_or_claimed == 1
    assert metrics.oracle_quality.billing.outbox_manual_review == 1
    assert metrics.oracle_quality.billing.outbox_pending_or_claimed == 1
    assert private_sentinel not in metrics.model_dump_json()
