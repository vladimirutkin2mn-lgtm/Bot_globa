"""Return analytics must mean a new local activity day, not a repeated update."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.analytics import AnalyticsEvent
from app.db.base import Base
from app.providers.analytics_postgres import (
    PostgresAnalyticsClient,
    _repeat_activity_properties,
)
from app.providers.numa_product_analytics import (
    ProductFlow,
    ProductFunnelEvent,
    ProductSource,
)
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution

pytestmark = pytest.mark.postgres


@pytest.fixture
async def repeat_analytics_postgres() -> AsyncIterator[
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine, async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _entry_properties(entity_id: str, *, timezone: str = "Europe/Moscow") -> dict[str, str]:
    return {
        "event_version": "numa-product-funnel-v1",
        "entity_id": entity_id,
        "flow": "personal",
        "source": "normal_start",
        "scenario_version": "personal_oracle_v1",
        "experiment_assignment": "control",
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": "false",
        "calculation_timezone": timezone,
    }


def test_return_day_uses_local_calendar_not_elapsed_24_hours() -> None:
    subject_id = str(uuid4())
    first = datetime(2026, 9, 12, 20, 30, tzinfo=UTC)
    current = datetime(2026, 9, 12, 22, 0, tzinfo=UTC)

    properties = _repeat_activity_properties(
        _entry_properties(str(uuid4())),
        subject_id,
        first,
        current,
    )

    assert properties is not None
    assert properties["activity_kind"] == "return"
    assert properties["day_bucket"] == "d1"


def test_same_local_day_is_not_repeat_activity() -> None:
    now = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)

    assert (
        _repeat_activity_properties(
            _entry_properties(str(uuid4())),
            str(uuid4()),
            now - timedelta(hours=2),
            now,
        )
        is None
    )


async def test_first_new_entry_on_return_day_emits_one_repeat_event(
    repeat_analytics_postgres: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = repeat_analytics_postgres
    client = PostgresAnalyticsClient(sessions)
    analytics = NumaProductAnalytics(client)
    user_id = uuid4()
    attribution = ProductAttribution(
        flow=ProductFlow.PERSONAL,
        source=ProductSource.NORMAL_START,
        scenario_version="personal_oracle_v1",
    )
    first_entity, return_entity = uuid4(), uuid4()

    await analytics.track(
        user_id=user_id,
        entity_id=first_entity,
        event=ProductFunnelEvent.ENTRY,
        attribution=attribution,
    )
    async with sessions.begin() as session:
        await session.execute(
            update(AnalyticsEvent)
            .where(AnalyticsEvent.event_name == ProductFunnelEvent.ENTRY.value)
            .values(created_at=datetime.now(UTC) - timedelta(days=2))
        )

    await analytics.track(
        user_id=user_id,
        entity_id=return_entity,
        event=ProductFunnelEvent.ENTRY,
        attribution=attribution,
    )
    # Telegram retries or duplicate runtime updates must not create another business return.
    await analytics.track(
        user_id=user_id,
        entity_id=return_entity,
        event=ProductFunnelEvent.ENTRY,
        attribution=attribution,
    )

    async with sessions() as session:
        repeats = list(
            (
                await session.scalars(
                    select(AnalyticsEvent).where(
                        AnalyticsEvent.event_name == ProductFunnelEvent.REPEAT_ACTIVITY.value
                    )
                )
            ).all()
        )

    assert len(repeats) == 1
    assert repeats[0].subject_id == str(user_id)
    assert repeats[0].properties["activity_kind"] == "return"
    assert repeats[0].properties["day_bucket"] == "d2_6"
    assert repeats[0].properties["test_traffic"] == "false"
