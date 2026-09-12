"""Regression coverage for reading-scoped Numa acquisition attribution."""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.analytics import AnalyticsEvent
from app.db.base import Base
from app.providers.analytics import OracleProductEvent, PRODUCT_EVENT_TAXONOMY_VERSION
from app.providers.analytics_postgres import PostgresAnalyticsClient
from app.providers.numa_product_analytics import (
    NUMA_PRODUCT_EVENT_VERSION,
    ProductFlow,
    ProductFunnelEvent,
    ProductSource,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
async def analytics_postgres() -> AsyncIterator[
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


def _entry_properties(entity_id: str, source: ProductSource) -> dict[str, str]:
    return {
        "event_version": NUMA_PRODUCT_EVENT_VERSION,
        "entity_id": entity_id,
        "flow": ProductFlow.PERSONAL.value,
        "source": source.value,
        "scenario_version": "tarot_reader_v1",
        "experiment_assignment": "control",
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": "false",
        "calculation_timezone": "UTC",
    }


def _reading_properties(reading_id: str) -> dict[str, str]:
    return {
        "event_version": PRODUCT_EVENT_TAXONOMY_VERSION,
        "reading_id": reading_id,
        "persona_code": "tarot_reader",
        "topic_code": "general",
    }


async def test_later_personal_entry_does_not_rewrite_existing_reading_source(
    analytics_postgres: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = analytics_postgres
    client = PostgresAnalyticsClient(sessions)
    user_id = str(uuid4())
    first_reading_id, second_reading_id = str(uuid4()), str(uuid4())

    await client.track(
        user_id,
        ProductFunnelEvent.ENTRY.value,
        _entry_properties(str(uuid4()), ProductSource.GROUP_COMPATIBILITY),
    )
    await client.track(
        user_id,
        OracleProductEvent.READING_STARTED.value,
        _reading_properties(first_reading_id),
    )

    await client.track(
        user_id,
        ProductFunnelEvent.ENTRY.value,
        _entry_properties(str(uuid4()), ProductSource.NORMAL_START),
    )
    await client.track(
        user_id,
        OracleProductEvent.READING_PREVIEW_READY.value,
        _reading_properties(first_reading_id),
    )

    await client.track(
        user_id,
        OracleProductEvent.READING_STARTED.value,
        _reading_properties(second_reading_id),
    )
    await client.track(
        user_id,
        OracleProductEvent.READING_PREVIEW_READY.value,
        _reading_properties(second_reading_id),
    )

    async with sessions() as session:
        previews = list(
            (
                await session.scalars(
                    select(AnalyticsEvent).where(
                        AnalyticsEvent.event_name == ProductFunnelEvent.FREE_ANSWER_READY.value,
                        AnalyticsEvent.subject_id == user_id,
                    )
                )
            ).all()
        )

    sources_by_reading = {row.properties["entity_id"]: row.properties["source"] for row in previews}
    assert sources_by_reading == {
        first_reading_id: ProductSource.GROUP_COMPATIBILITY.value,
        second_reading_id: ProductSource.NORMAL_START.value,
    }
