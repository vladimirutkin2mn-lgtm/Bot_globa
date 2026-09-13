"""PostgreSQL feedback attribution must survive the real analytics boundary."""

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
from app.providers.analytics import OracleProductEvent
from app.providers.analytics_postgres import PostgresAnalyticsClient
from app.services.oracle_product_analytics import OracleProductAnalytics

pytestmark = pytest.mark.postgres


@pytest.fixture
async def feedback_postgres() -> AsyncIterator[
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


async def test_feedback_persists_reading_stage_and_first_reaction_per_stage(
    feedback_postgres: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = feedback_postgres
    analytics = OracleProductAnalytics(PostgresAnalyticsClient(sessions))
    user_id, reading_id = uuid4(), uuid4()

    await analytics.track(
        user_id,
        OracleProductEvent.READING_FEEDBACK_SUBMITTED,
        {
            "reading_id": reading_id,
            "stage_code": "preview",
            "reaction_code": "hit",
        },
    )
    # A repeated or changed tap on the same reading stage is intentionally first-write-wins.
    await analytics.track(
        user_id,
        OracleProductEvent.READING_FEEDBACK_SUBMITTED,
        {
            "reading_id": reading_id,
            "stage_code": "preview",
            "reaction_code": "miss_unclear",
        },
    )
    # Full feedback is a different product stage and remains independently measurable.
    await analytics.track(
        user_id,
        OracleProductEvent.READING_FEEDBACK_SUBMITTED,
        {
            "reading_id": reading_id,
            "stage_code": "full",
            "reaction_code": "hit",
        },
    )

    async with sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(AnalyticsEvent)
                    .where(
                        AnalyticsEvent.event_name
                        == OracleProductEvent.READING_FEEDBACK_SUBMITTED.value
                    )
                    .order_by(AnalyticsEvent.idempotency_key)
                )
            ).all()
        )

    assert len(rows) == 2
    by_stage = {row.properties["stage_code"]: row for row in rows}
    assert by_stage["preview"].properties == {
        "event_version": "oracle-product-events-v1",
        "reaction_code": "hit",
        "reading_id": str(reading_id),
        "stage_code": "preview",
    }
    assert by_stage["full"].properties["reading_id"] == str(reading_id)
    assert by_stage["full"].properties["reaction_code"] == "hit"
    assert by_stage["preview"].subject_id == str(user_id)
    assert by_stage["full"].subject_id == str(user_id)
