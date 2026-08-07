"""Real-PostgreSQL admission limits for ORA-604."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.domain.reading import ReadingDraftRequest
from app.services.oracle_release_controls import (
    OracleReleaseControls,
    OracleReleaseDecisionCode,
)


@pytest.fixture
async def release_db() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    schema = f"oracle_release_test_{uuid4().hex}"
    admin = create_async_engine(url)
    await _schema_sql(admin, f'CREATE SCHEMA "{schema}"')
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        await _schema_sql(admin, f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.dispose()


async def _schema_sql(engine: AsyncEngine, statement: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(statement))


def _controls(
    *,
    rate_limit: int = 0,
    rate_window_seconds: int = 60,
    daily_cap: int = 0,
    reservation: int = 0,
) -> OracleReleaseControls:
    return OracleReleaseControls(
        enabled=True,
        rollout_percentage=100,
        rollout_seed="postgres-release-v1",
        disabled_personas=frozenset(),
        disabled_engines=frozenset(),
        generation_rate_limit=rate_limit,
        generation_rate_window_seconds=rate_window_seconds,
        daily_spend_cap_microusd=daily_cap,
        max_reserved_cost_microusd_per_reading=reservation,
    )


def _request() -> ReadingDraftRequest:
    return ReadingDraftRequest(
        persona_code="tarot_reader",
        topic="decision",
        question="Synthetic release-control fixture",
        context=None,
        engine_version="symbolic-v1",
        prompt_version="tarot-reader-v2",
        schema_version="reading-result-v1",
    )


async def _seed_user_and_persona(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    async with sessions.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Release")
        persona = Persona(
            code="tarot_reader",
            display_name="Tarot Reader",
            prompt_version="tarot-reader-v2",
            schema_version="reading-result-v1",
            enabled=True,
        )
        session.add_all((user, persona))
        await session.flush()
        return user.id, persona.id


async def _seed_reading(
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    persona_id: UUID,
    created_at: datetime,
) -> None:
    async with sessions.begin() as session:
        session.add(
            Reading(
                user_id=user_id,
                persona_id=persona_id,
                topic="decision",
                status="draft",
                access_level="none",
                cost_units=0,
                engine_version="symbolic-v1",
                prompt_version="tarot-reader-v2",
                schema_version="reading-result-v1",
                created_at=created_at,
            )
        )


@pytest.mark.asyncio
async def test_rate_limit_counts_recent_readings_across_transactions(
    release_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, persona_id = await _seed_user_and_persona(release_db)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    await _seed_reading(
        release_db,
        user_id=user_id,
        persona_id=persona_id,
        created_at=now - timedelta(seconds=20),
    )
    await _seed_reading(
        release_db,
        user_id=user_id,
        persona_id=persona_id,
        created_at=now - timedelta(seconds=10),
    )
    await _seed_reading(
        release_db,
        user_id=user_id,
        persona_id=persona_id,
        created_at=now - timedelta(minutes=5),
    )
    controls = _controls(rate_limit=2, rate_window_seconds=60)

    async with release_db.begin() as session:
        decision = await controls.authorize_draft(session, user_id, _request(), now=now)

    assert decision.code is OracleReleaseDecisionCode.RATE_LIMITED


@pytest.mark.asyncio
async def test_daily_spend_reservation_allows_boundary_then_blocks_next_reading(
    release_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, persona_id = await _seed_user_and_persona(release_db)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    await _seed_reading(
        release_db,
        user_id=user_id,
        persona_id=persona_id,
        created_at=now - timedelta(hours=1),
    )
    controls = _controls(daily_cap=200, reservation=100)

    async with release_db.begin() as session:
        boundary = await controls.authorize_draft(session, user_id, _request(), now=now)
    assert boundary.code is OracleReleaseDecisionCode.ALLOWED

    await _seed_reading(
        release_db,
        user_id=user_id,
        persona_id=persona_id,
        created_at=now,
    )
    async with release_db.begin() as session:
        blocked = await controls.authorize_draft(session, user_id, _request(), now=now)

    assert blocked.code is OracleReleaseDecisionCode.SPEND_CAP_REACHED


@pytest.mark.asyncio
async def test_daily_spend_cap_resets_at_utc_midnight(
    release_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, persona_id = await _seed_user_and_persona(release_db)
    now = datetime(2026, 8, 7, 0, 5, tzinfo=UTC)
    await _seed_reading(
        release_db,
        user_id=user_id,
        persona_id=persona_id,
        created_at=now - timedelta(minutes=10),
    )
    controls = _controls(daily_cap=100, reservation=100)

    async with release_db.begin() as session:
        decision = await controls.authorize_draft(session, user_id, _request(), now=now)

    assert decision.code is OracleReleaseDecisionCode.ALLOWED
