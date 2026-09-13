"""Decision report must join feedback attribution and exclude marked test traffic."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.analytics import AnalyticsEvent
from app.db.base import Base
from app.services.numa_decision_report import numa_decision_report

pytestmark = pytest.mark.postgres


@pytest.fixture
async def report_postgres() -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine, async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _typed_properties(
    entity_id: str,
    *,
    source: str,
    flow: str,
    variant: str = "control",
    test_traffic: str = "false",
) -> dict[str, str]:
    return {
        "event_version": "numa-product-funnel-v1",
        "entity_id": entity_id,
        "flow": flow,
        "source": source,
        "scenario_version": "synthetic_v1",
        "experiment_assignment": variant,
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": test_traffic,
        "calculation_timezone": "Europe/Moscow",
    }


def _event(
    event_name: str,
    subject_id: str | None,
    properties: dict[str, str],
    created_at: datetime,
) -> AnalyticsEvent:
    return AnalyticsEvent(
        event_name=event_name,
        subject_id=subject_id,
        properties=properties,
        idempotency_key=f"test:{event_name}:{uuid4()}",
        correlation_id=f"test-{uuid4()}",
        created_at=created_at,
    )


async def test_report_segments_real_traffic_and_attributes_feedback(
    report_postgres: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = report_postgres
    now = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    user_id, test_user_id = str(uuid4()), str(uuid4())
    reading_id = str(uuid4())
    base = _typed_properties(reading_id, source="normal_start", flow="personal")
    personal_events = [
        "numa_entry",
        "numa_question_accepted",
        "numa_free_answer_delivered",
        "numa_paywall_shown",
        "numa_checkout_started",
        "numa_purchase_confirmed",
        "numa_full_unlocked",
        "numa_repeat_activity",
    ]
    rows = [_event(name, user_id, dict(base), now) for name in personal_events]
    rows.extend(
        [
            _event(
                "reading_feedback_submitted",
                user_id,
                {
                    "event_version": "oracle-product-events-v1",
                    "reading_id": reading_id,
                    "stage_code": "preview",
                    "reaction_code": "hit",
                },
                now,
            ),
            _event(
                "reading_feedback_submitted",
                user_id,
                {
                    "event_version": "oracle-product-events-v1",
                    "reading_id": reading_id,
                    "stage_code": "full",
                    "reaction_code": "miss_unclear",
                },
                now,
            ),
        ]
    )

    daily_id = str(uuid4())
    daily = _typed_properties(daily_id, source="daily_horoscope", flow="daily")
    rows.extend(
        [
            _event("numa_daily_delivered", user_id, dict(daily), now),
            _event("numa_daily_action", user_id, dict(daily), now),
        ]
    )

    share_id = str(uuid4())
    shared = _typed_properties(share_id, source="shared_insight", flow="personal")
    rows.extend(
        [
            _event("numa_entry", user_id, dict(shared), now),
            _event("numa_share_intent", user_id, dict(shared), now),
            _event("numa_recipient_entry", str(uuid4()), dict(shared), now),
        ]
    )

    test_reading_id = str(uuid4())
    test_props = _typed_properties(
        test_reading_id,
        source="test_campaign",
        flow="personal",
        test_traffic="true",
    )
    rows.extend(
        [
            _event("numa_entry", test_user_id, dict(test_props), now),
            _event("numa_purchase_confirmed", test_user_id, dict(test_props), now),
            _event("numa_question_accepted", test_user_id, dict(test_props), now),
            _event(
                "reading_feedback_submitted",
                test_user_id,
                {
                    "event_version": "oracle-product-events-v1",
                    "reading_id": test_reading_id,
                    "stage_code": "preview",
                    "reaction_code": "hit",
                },
                now,
            ),
        ]
    )

    async with sessions.begin() as session:
        session.add_all(rows)

    async with sessions() as session:
        report = await numa_decision_report(
            session,
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(hours=1),
        )

    assert {(row.source, row.experiment_assignment, row.flow) for row in report} == {
        ("normal_start", "control", "personal"),
        ("daily_horoscope", "control", "daily"),
        ("shared_insight", "control", "personal"),
    }
    personal = next(row for row in report if row.source == "normal_start")
    assert personal.entries == 1
    assert personal.entry_users == 1
    assert personal.questions_accepted == 1
    assert personal.free_answers_delivered == 1
    assert personal.purchase_users == 1
    assert personal.repeat_users == 1
    assert personal.preview_feedback == 1
    assert personal.preview_hits == 1
    assert personal.full_feedback == 1
    assert personal.full_hits == 0
    assert personal.free_delivery_rate == 1.0
    assert personal.purchase_user_rate == 1.0
    assert personal.repeat_user_rate == 1.0
    assert personal.preview_hit_rate == 1.0
    assert personal.full_hit_rate == 0.0

    daily_row = next(row for row in report if row.source == "daily_horoscope")
    assert daily_row.daily_delivered == 1
    assert daily_row.daily_actions == 1
    assert daily_row.daily_action_rate == 1.0

    share_row = next(row for row in report if row.source == "shared_insight")
    assert share_row.share_intents == 1
    assert share_row.recipient_entries == 1
    assert share_row.share_recipient_rate == 1.0


async def test_report_rejects_an_inverted_window(
    report_postgres: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = report_postgres
    now = datetime.now(UTC)

    async with sessions() as session:
        with pytest.raises(ValueError, match="report start must be before report end"):
            await numa_decision_report(session, start_at=now, end_at=now)
