"""PostgreSQL integration coverage for immutable acquisition attribution."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.acquisition_models import AcquisitionAttribution
from app.db.base import Base
from app.db.models import User
from app.services.acquisition_attribution import AcquisitionAttributionRepository

pytestmark = pytest.mark.postgres


@pytest.fixture
async def postgres() -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine, async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _create_user(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    async with sessions.begin() as session:
        user = User(telegram_user_id=9001, first_name="Dogfood")
        session.add(user)
        await session.flush()
        return user.id


async def test_capture_first_touch_does_not_overwrite_existing_experiment(
    postgres: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = postgres
    user_id = await _create_user(sessions)
    first_experiment = uuid4()
    later_experiment = uuid4()

    async with sessions() as session:
        repository = AcquisitionAttributionRepository(session)
        first, created = await repository.capture_first_touch(
            user_id=user_id, experiment_id=first_experiment
        )
    async with sessions() as session:
        repository = AcquisitionAttributionRepository(session)
        repeated, created_again = await repository.capture_first_touch(
            user_id=user_id, experiment_id=later_experiment
        )

    assert created
    assert not created_again
    assert first.experiment_id == first_experiment
    assert repeated.experiment_id == first_experiment


async def test_concurrent_first_touch_attempts_converge_on_one_row(
    postgres: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = postgres
    user_id = await _create_user(sessions)
    experiment_ids = [uuid4() for _ in range(12)]

    async def capture(experiment_id: UUID) -> tuple[UUID, bool]:
        async with sessions() as session:
            repository = AcquisitionAttributionRepository(session)
            attribution, created = await repository.capture_first_touch(
                user_id=user_id, experiment_id=experiment_id
            )
            return attribution.experiment_id, created

    results = await asyncio.gather(*(capture(experiment_id) for experiment_id in experiment_ids))

    async with sessions() as session:
        rows = await session.scalar(select(func.count()).select_from(AcquisitionAttribution))
        stored = await session.scalar(
            select(AcquisitionAttribution).where(AcquisitionAttribution.user_id == user_id)
        )

    assert rows == 1
    assert sum(1 for _, created in results if created) == 1
    assert stored is not None
    assert stored.experiment_id in experiment_ids
    assert all(experiment_id == stored.experiment_id for experiment_id, _ in results)
