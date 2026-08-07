"""PostgreSQL invariants for versioned oracle product-event deduplication."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.observability.context import reset_correlation_id, set_correlation_id
from app.providers.analytics import (
    PRODUCT_EVENT_TAXONOMY_VERSION,
    OracleProductEvent,
)
from app.providers.analytics_postgres import PostgresAnalyticsClient
from app.services.oracle_product_analytics import OracleProductAnalytics
from tests.payment_postgres_helpers import payment_db  # noqa: F401


async def test_oracle_events_deduplicate_by_reading_memory_item_and_action(
    payment_db: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    analytics = OracleProductAnalytics(PostgresAnalyticsClient(payment_db))
    user_id = uuid4()
    reading_id = uuid4()
    first_memory_id, second_memory_id = uuid4(), uuid4()

    _, token = set_correlation_id("oracle-reading-transition")
    try:
        for _ in range(2):
            await analytics.track(
                user_id,
                OracleProductEvent.READING_STARTED,
                {
                    "reading_id": reading_id,
                    "persona_code": "tarot_reader",
                    "topic_code": "decision",
                    "engine_version": "symbolic-v1",
                    "prompt_version": "tarot-reader-v2",
                    "schema_version": "reading-result-v1",
                },
            )
        await analytics.track(
            user_id,
            OracleProductEvent.READING_PREVIEW_READY,
            {
                "reading_id": reading_id,
                "persona_code": "tarot_reader",
                "topic_code": "decision",
                "attempt_count": 1,
                "repair_used": False,
                "memory_count": 2,
            },
        )
        for memory_item_id in (first_memory_id, second_memory_id):
            await analytics.track(
                user_id,
                OracleProductEvent.MEMORY_ITEM_CREATED,
                {
                    "memory_item_id": memory_item_id,
                    "memory_kind": "personal_goal",
                    "claim_basis": "user_stated",
                    "source_type": "user_explicit",
                },
            )
    finally:
        reset_correlation_id(token)

    for correlation_id in ("persona-action-one", "persona-action-two"):
        _, token = set_correlation_id(correlation_id)
        try:
            await analytics.track(
                user_id,
                OracleProductEvent.PERSONA_SELECTED,
                {"persona_code": "astrologer", "topic_code": "natal_profile"},
            )
            await analytics.track(
                user_id,
                OracleProductEvent.PERSONA_SELECTED,
                {"persona_code": "astrologer", "topic_code": "natal_profile"},
            )
        finally:
            reset_correlation_id(token)

    async with payment_db() as session:
        rows = list(
            (
                await session.scalars(
                    select(AnalyticsEvent).order_by(AnalyticsEvent.idempotency_key)
                )
            ).all()
        )

    assert len(rows) == 6
    assert {row.idempotency_key for row in rows} == {
        f"reading_started:{reading_id}",
        f"reading_preview_ready:{reading_id}",
        f"memory_item_created:{first_memory_id}",
        f"memory_item_created:{second_memory_id}",
        "persona_selected:persona-action-one",
        "persona_selected:persona-action-two",
    }
    assert all(row.subject_id == str(user_id) for row in rows)
    assert all(row.properties["event_version"] == PRODUCT_EVENT_TAXONOMY_VERSION for row in rows)
    serialized = str([row.properties for row in rows])
    assert "question" not in serialized
    assert "reading_text" not in serialized
    assert "birth_date" not in serialized
