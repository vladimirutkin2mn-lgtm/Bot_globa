"""PostgreSQL delivery invariants for the voluntary common daily digest."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopePreference
from app.db.models import User
from app.domain.daily_horoscope import DailyHoroscopeMode
from app.providers.analytics import NoOpAnalyticsClient
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.data_deletion import DataDeletionOutcome, DataDeletionService

pytestmark = pytest.mark.postgres


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Daily")
        session.add(user)
        await session.flush()
        return user


async def test_opt_in_is_leased_once_and_rescheduled_after_delivery(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 975001)
    service = DailyHoroscopePreferenceService(payment_db)
    before = datetime(2026, 8, 13, 4, 59, tzinfo=UTC)

    default = await service.current(user.id)
    assert default.mode is DailyHoroscopeMode.ON_REQUEST
    assert default.next_delivery_at is None

    configured = await service.configure(user.id, DailyHoroscopeMode.MORNING, now=before)
    assert configured.next_delivery_at == datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
    assert await service.claim_due(now=before) is None

    due = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
    claim = await service.claim_due(now=due, lease_seconds=120)
    assert claim is not None
    assert claim.user_id == user.id
    assert claim.telegram_user_id == 975001
    assert claim.delivery_date.isoformat() == "2026-08-13"
    assert await service.claim_due(now=due, lease_seconds=120) is None

    assert await service.complete(claim, now=datetime(2026, 8, 13, 5, 1, tzinfo=UTC))
    current = await service.current(user.id)
    assert current.next_delivery_at == datetime(2026, 8, 14, 5, 0, tzinfo=UTC)


async def test_opt_out_invalidates_an_in_flight_delivery_claim(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 975002)
    service = DailyHoroscopePreferenceService(payment_db)
    due = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 12, 5, 1, tzinfo=UTC),
    )
    claim = await service.claim_due(now=due)
    assert claim is not None

    disabled = await service.configure(user.id, DailyHoroscopeMode.DISABLED, now=due)

    assert disabled.next_delivery_at is None
    assert not await service.complete(claim, now=due)
    assert await service.claim_due(now=due) is None


async def test_account_deletion_removes_daily_delivery_preference(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 975003)
    await DailyHoroscopePreferenceService(payment_db).configure(
        user.id,
        DailyHoroscopeMode.EVENING,
        now=datetime(2026, 8, 13, 5, 0, tzinfo=UTC),
    )

    async with payment_db() as session:
        outcome = await DataDeletionService(session, NoOpAnalyticsClient()).delete_account(user.id)
    async with payment_db() as session:
        preference = await session.get(DailyHoroscopePreference, user.id)

    assert outcome is DataDeletionOutcome.DELETED
    assert preference is None
