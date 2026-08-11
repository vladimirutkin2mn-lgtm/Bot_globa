"""PostgreSQL regressions for expiring the unused part of a subscription period."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CreditTransaction, User
from app.db.subscription_models import SubscriptionPeriod
from app.services.credits_service import CreditsService, ExpiryOutcome
from app.services.subscription_credit_expiry import expire_closed_periods
from app.services.subscription_lifecycle import (
    PaidSubscriptionPeriod,
    PeriodApplyOutcome,
    SubscriptionLifecycleService,
)

pytestmark = pytest.mark.postgres


async def _user(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    async with sessions.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Subscriber")
        session.add(user)
        await session.flush()
        return user.id


def _closed_period(credits: int = 30) -> PaidSubscriptionPeriod:
    """A period that ended yesterday, so the sweep is due to settle it."""

    end = datetime.now(UTC) - timedelta(days=1)
    start = end - timedelta(days=30)
    return PaidSubscriptionPeriod(
        provider="stripe",
        provider_customer_id="cus-expiry",
        provider_subscription_id="sub-expiry",
        provider_invoice_id="invoice-expiry",
        provider_payment_id="payment-expiry",
        product_code="subscription_monthly",
        product_version=2,
        market="INTERNATIONAL",
        currency="EUR",
        amount_minor=699,
        credits=credits,
        price_reference="catalog:subscription_monthly:eur:v2",
        period_start=start,
        period_end=end,
        paid_at=start,
        consent_version="billing-v1",
        live_mode=False,
    )


async def _period_id(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    async with sessions() as session:
        value = await session.scalar(select(SubscriptionPeriod.id))
        assert value is not None
        return value


async def _balance(sessions: async_sessionmaker[AsyncSession], user_id: UUID) -> int:
    async with sessions() as session:
        return int(
            await session.scalar(
                select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                    CreditTransaction.user_id == user_id
                )
            )
            or 0
        )


async def _granted_subscription_period(
    sessions: async_sessionmaker[AsyncSession], credits: int = 30
) -> tuple[UUID, UUID]:
    user_id = await _user(sessions)
    lifecycle = SubscriptionLifecycleService(sessions)
    outcome = await lifecycle.apply_paid_period(user_id, _closed_period(credits))
    assert outcome is PeriodApplyOutcome.APPLIED
    return user_id, await _period_id(sessions)


@pytest.mark.asyncio
async def test_unused_subscription_credits_lapse_when_the_period_closes(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, period_id = await _granted_subscription_period(payment_db)
    assert await _balance(payment_db, user_id) == 30

    result = await CreditsService(payment_db).expire_subscription_period(period_id)

    assert result.outcome is ExpiryOutcome.EXPIRED
    assert result.expired == 30
    assert await _balance(payment_db, user_id) == 0


@pytest.mark.asyncio
async def test_purchased_credits_survive_a_subscription_expiry(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """A subscription lends; a purchase does not. Only the loan is recalled."""

    user_id, period_id = await _granted_subscription_period(payment_db)
    credits = CreditsService(payment_db)
    await credits.grant(user_id, 7, "test:purchased-outright")

    result = await credits.expire_subscription_period(period_id)

    assert result.outcome is ExpiryOutcome.EXPIRED
    assert result.expired == 30
    assert await _balance(payment_db, user_id) == 7


@pytest.mark.asyncio
async def test_spending_is_charged_against_the_lapsing_credits_first(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, period_id = await _granted_subscription_period(payment_db)
    credits = CreditsService(payment_db)
    await credits.grant(user_id, 5, "test:purchased-outright")
    await credits.adjustment(user_id, -12, "test:twelve-readings")

    result = await credits.expire_subscription_period(period_id)

    # 30 lent + 5 owned - 12 spent = 23 held, of which 5 are the user's own.
    assert result.expired == 18
    assert await _balance(payment_db, user_id) == 5


@pytest.mark.asyncio
async def test_expiry_can_never_drive_a_balance_negative(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """The user spent everything the period lent and some of their own on top."""

    user_id, period_id = await _granted_subscription_period(payment_db)
    credits = CreditsService(payment_db)
    await credits.grant(user_id, 5, "test:purchased-outright")
    await credits.adjustment(user_id, -33, "test:thirty-three-readings")

    result = await credits.expire_subscription_period(period_id)

    assert result.outcome is ExpiryOutcome.NOTHING_TO_EXPIRE
    assert await _balance(payment_db, user_id) == 2


@pytest.mark.asyncio
async def test_expiry_never_takes_more_than_the_period_lent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, period_id = await _granted_subscription_period(payment_db, credits=5)
    credits = CreditsService(payment_db)
    await credits.grant(user_id, 40, "test:large-purchase")

    result = await credits.expire_subscription_period(period_id)

    assert result.expired == 5
    assert await _balance(payment_db, user_id) == 40


@pytest.mark.asyncio
async def test_concurrent_expiry_attempts_settle_the_period_once(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, period_id = await _granted_subscription_period(payment_db)
    credits = CreditsService(payment_db)

    outcomes = [
        result.outcome
        for result in await asyncio.gather(
            *(credits.expire_subscription_period(period_id) for _ in range(8))
        )
    ]

    assert outcomes.count(ExpiryOutcome.EXPIRED) == 1
    assert outcomes.count(ExpiryOutcome.ALREADY_EXPIRED) == 7
    async with payment_db() as session:
        expiries = await session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.type == "expiry")
        )
    assert expiries == 1
    assert await _balance(payment_db, user_id) == 0


@pytest.mark.asyncio
async def test_an_open_period_is_left_alone(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _user(payment_db)
    lifecycle = SubscriptionLifecycleService(payment_db)
    end = datetime.now(UTC) + timedelta(days=10)
    open_period = _closed_period()
    await lifecycle.apply_paid_period(
        user_id,
        PaidSubscriptionPeriod(
            **{
                **open_period.__dict__,
                "period_start": end - timedelta(days=30),
                "period_end": end,
            }
        ),
    )

    result = await CreditsService(payment_db).expire_subscription_period(
        await _period_id(payment_db)
    )

    assert result.outcome is ExpiryOutcome.PERIOD_STILL_OPEN
    assert await _balance(payment_db, user_id) == 30


@pytest.mark.asyncio
async def test_the_sweep_settles_every_closed_period_and_is_repeatable(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, _ = await _granted_subscription_period(payment_db)
    credits = CreditsService(payment_db)

    first = await expire_closed_periods(payment_db, credits)
    second = await expire_closed_periods(payment_db, credits)

    assert (first.expired_periods, first.expired_credits) == (1, 30)
    assert (second.examined, second.expired_periods) == (0, 0)
    assert await _balance(payment_db, user_id) == 0
