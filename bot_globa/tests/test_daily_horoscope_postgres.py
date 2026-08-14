"""PostgreSQL delivery invariants for the default-on common daily digest."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopePreference
from app.db.models import User
from app.domain.daily_horoscope import DailyHoroscopeMode
from app.providers.analytics import NoOpAnalyticsClient
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.data_deletion import DataDeletionOutcome, DataDeletionService
from app.services.onboarding import CURRENT_CONSENT_VERSION

pytestmark = pytest.mark.postgres


async def _user(
    sessions: async_sessionmaker[AsyncSession],
    telegram_id: int,
    *,
    consent: str | None = CURRENT_CONSENT_VERSION,
) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Daily", consent_version=consent)
        session.add(user)
        await session.flush()
        return user


async def test_default_morning_is_leased_once_and_rescheduled_after_delivery(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 975001)
    service = DailyHoroscopePreferenceService(payment_db)
    before = datetime(2026, 8, 13, 4, 59, tzinfo=UTC)

    await service.ensure_default(user.id, now=before)
    default = await service.current(user.id)
    assert default.mode is DailyHoroscopeMode.MORNING
    assert default.next_delivery_at == datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
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


async def test_an_expired_lease_does_not_deliver_the_same_day_twice(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """A worker killed between the send and the completion must not repeat the digest."""

    user = await _user(payment_db, 975005)
    service = DailyHoroscopePreferenceService(payment_db)
    due = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 13, 4, 59, tzinfo=UTC),
    )
    claim = await service.claim_due(now=due, lease_seconds=120)
    assert claim is not None

    # Do not call complete(): this is the actual process-death window after Telegram may
    # have accepted the message but before the worker acknowledged the claim.
    reserved = await service.current(user.id)
    assert reserved.next_delivery_at == datetime(2026, 8, 14, 5, 0, tzinfo=UTC)

    assert await service.claim_due(now=datetime(2026, 8, 13, 9, 0, tzinfo=UTC)) is None

    tomorrow = await service.claim_due(now=datetime(2026, 8, 14, 5, 0, tzinfo=UTC))
    assert tomorrow is not None
    assert tomorrow.delivery_date.isoformat() == "2026-08-14"


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


async def test_moscow_difference_moves_the_same_local_08_schedule(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 975006)
    service = DailyHoroscopePreferenceService(payment_db)
    before = datetime(2026, 8, 13, 2, 59, tzinfo=UTC)
    await service.ensure_default(user.id, now=before)

    configured = await service.set_moscow_time_difference(user.id, 2, now=before)

    assert configured.mode is DailyHoroscopeMode.MORNING
    assert configured.timezone == "Etc/GMT-5"
    assert configured.next_delivery_at == datetime(2026, 8, 13, 3, 0, tzinfo=UTC)
    assert await service.claim_due(now=before) is None
    claim = await service.claim_due(now=datetime(2026, 8, 13, 3, 0, tzinfo=UTC))
    assert claim is not None
    assert claim.delivery_date.isoformat() == "2026-08-13"


async def test_a_provisioned_schedule_waits_for_consent_and_delivers_after_it(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """A default-on row is created at /start, before the terms screen is answered."""

    user = await _user(payment_db, 975007, consent=None)
    service = DailyHoroscopePreferenceService(payment_db)
    due = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
    await service.ensure_default(user.id, now=datetime(2026, 8, 13, 4, 59, tzinfo=UTC))

    assert await service.claim_due(now=due) is None

    async with payment_db.begin() as session:
        stored = await session.get(User, user.id)
        assert stored is not None
        stored.consent_version = CURRENT_CONSENT_VERSION

    claim = await service.claim_due(now=due)
    assert claim is not None
    assert claim.user_id == user.id


async def test_reading_the_settings_never_provisions_or_locks(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """The settings screen is a read: it must not enrol anyone as a side effect."""

    user = await _user(payment_db, 975008)
    service = DailyHoroscopePreferenceService(payment_db)

    view = await service.current(user.id)

    assert view.mode is DailyHoroscopeMode.MORNING
    assert view.next_delivery_at is None
    async with payment_db() as session:
        assert await session.get(DailyHoroscopePreference, user.id) is None
    assert await service.claim_due(now=datetime(2026, 8, 13, 5, 0, tzinfo=UTC)) is None


async def test_reading_the_settings_of_a_deleted_account_reports_the_default(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """`current` must not raise where the old read-only version returned a default view."""

    user = await _user(payment_db, 975009)
    service = DailyHoroscopePreferenceService(payment_db)
    await service.ensure_default(user.id, now=datetime(2026, 8, 13, 4, 59, tzinfo=UTC))
    async with payment_db() as session:
        await DataDeletionService(session, NoOpAnalyticsClient()).delete_account(user.id)

    view = await service.current(user.id)

    assert view.mode is DailyHoroscopeMode.MORNING
    assert view.next_delivery_at is None


async def test_account_deletion_removes_daily_delivery_preference(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 975003)
    await DailyHoroscopePreferenceService(payment_db).configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 13, 5, 0, tzinfo=UTC),
    )

    async with payment_db() as session:
        outcome = await DataDeletionService(session, NoOpAnalyticsClient()).delete_account(user.id)
    async with payment_db() as session:
        preference = await session.get(DailyHoroscopePreference, user.id)

    assert outcome is DataDeletionOutcome.DELETED
    assert preference is None
