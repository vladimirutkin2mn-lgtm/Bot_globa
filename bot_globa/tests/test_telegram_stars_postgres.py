"""Exactly-once Telegram Stars payments on real PostgreSQL."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    BillingCustomer,
    CreditTransaction,
    PaymentOrder,
    ProviderWebhookEvent,
    Subscription,
    User,
)
from app.db.subscription_models import SubscriptionPeriod
from app.domain.billing import BillingCatalog
from app.providers.payments.subscription_gateway import SubscriptionStateFact
from app.services.payment_completion_service import PaymentCompletionService
from app.services.subscription_event_processor import SubscriptionEventProcessor
from app.services.subscription_lifecycle import SubscriptionLifecycleService
from app.services.telegram_stars_service import (
    TelegramStarsPaymentFact,
    TelegramStarsPaymentService,
    TelegramStarsStateError,
)

pytestmark = pytest.mark.postgres


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://u:p@db/x",
        telegram_bot_token=SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        content_encryption_key=SecretStr("test-only-strong-content-key-32-bytes"),
        billing_enabled=True,
        payment_provider="production",
        telegram_stars_enabled=True,
        subscriptions_enabled=True,
        telegram_stars_amount_reading_single=75,
        telegram_stars_amount_reading_pack_5=300,
        telegram_stars_amount_subscription_monthly=450,
    )


def _service(
    sessions: async_sessionmaker[AsyncSession],
) -> TelegramStarsPaymentService:
    settings = _settings()
    lifecycle = SubscriptionLifecycleService(sessions)
    processor = SubscriptionEventProcessor(sessions, lifecycle, grace_period_days=3)
    return TelegramStarsPaymentService(
        sessions,
        settings,
        BillingCatalog(settings),
        PaymentCompletionService(sessions),
        processor,
    )


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Stars")
        session.add(user)
        await session.flush()
        return user


async def test_one_time_stars_payment_grants_once_under_replay(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 700_001)
    service = _service(payment_db)
    invoice = await service.create_invoice(user.id, "reading_single")
    decision = await service.validate_pre_checkout(
        700_001, "query-one", invoice.payload, "XTR", invoice.amount
    )
    mismatch = await service.validate_pre_checkout(
        700_001, "query-two", invoice.payload, "XTR", invoice.amount + 1
    )
    fact = TelegramStarsPaymentFact(
        currency="XTR",
        total_amount=invoice.amount,
        invoice_payload=invoice.payload,
        telegram_payment_charge_id="stars-charge-once",
        paid_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    outcomes = await asyncio.gather(*(service.complete_successful(700_001, fact) for _ in range(8)))

    assert decision.approved
    assert not mismatch.approved
    assert sum(value.outcome == "completed" for value in outcomes) == 1
    assert sum(value.outcome == "already_completed" for value in outcomes) == 7
    async with payment_db() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        assert await session.scalar(select(func.count()).select_from(CreditTransaction)) == 1
        order = await session.get(PaymentOrder, invoice.order_id)
        assert order is not None
        assert order.status == "completed"
        assert order.provider_payment_id == "stars-charge-once"


async def test_stars_subscription_applies_initial_and_renewal_period_once(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 700_002)
    service = _service(payment_db)
    invoice = await service.create_invoice(user.id, "subscription_monthly")
    first = TelegramStarsPaymentFact(
        currency="XTR",
        total_amount=invoice.amount,
        invoice_payload=invoice.payload,
        telegram_payment_charge_id="stars-subscription-initial",
        paid_at=datetime(2026, 8, 2, tzinfo=UTC),
        subscription_expiration_date=datetime(2026, 9, 1, tzinfo=UTC),
        is_recurring=True,
        is_first_recurring=True,
    )
    renewal = TelegramStarsPaymentFact(
        currency="XTR",
        total_amount=invoice.amount,
        invoice_payload=invoice.payload,
        telegram_payment_charge_id="stars-subscription-renewal",
        paid_at=datetime(2026, 9, 1, tzinfo=UTC),
        subscription_expiration_date=datetime(2026, 10, 1, tzinfo=UTC),
        is_recurring=True,
    )

    await service.complete_successful(700_002, first)
    await service.complete_successful(700_002, first)
    await service.complete_successful(700_002, renewal)
    await service.complete_successful(700_002, renewal)

    async with payment_db() as session:
        subscription = await session.scalar(select(Subscription))
        assert subscription is not None
        assert subscription.provider_subscription_id == "stars-subscription-initial"
        assert subscription.status == "active"
        assert await session.scalar(select(func.count()).select_from(SubscriptionPeriod)) == 2
        assert await session.scalar(select(func.count()).select_from(PaymentOrder)) == 2
        assert await session.scalar(select(func.count()).select_from(CreditTransaction)) == 2
        total = await session.scalar(select(func.sum(CreditTransaction.amount)))
        assert total == 60


async def test_mismatched_successful_payment_enters_durable_manual_review(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 700_003)
    service = _service(payment_db)
    invoice = await service.create_invoice(user.id, "reading_single")

    with pytest.raises(TelegramStarsStateError, match="does not match"):
        await service.complete_successful(
            700_003,
            TelegramStarsPaymentFact(
                currency="XTR",
                total_amount=invoice.amount + 1,
                invoice_payload=invoice.payload,
                telegram_payment_charge_id="stars-mismatch",
                paid_at=datetime(2026, 8, 12, tzinfo=UTC),
            ),
        )

    async with payment_db() as session:
        order = await session.get(PaymentOrder, invoice.order_id)
        event = await session.scalar(
            select(ProviderWebhookEvent).where(
                ProviderWebhookEvent.provider == "telegram_stars",
                ProviderWebhookEvent.provider_event_id == "stars-mismatch",
            )
        )
        assert order is not None and order.status == "manual_review"
        assert event is not None and event.status == "manual_review"
        assert event.payload_hash is not None and len(event.payload_hash) == 64
        assert await session.scalar(select(func.count()).select_from(CreditTransaction)) == 0


async def test_concurrent_pre_checkout_authorizes_one_charge_per_order(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """One order can back several invoice messages; only one of them may be charged."""
    user = await _user(payment_db, 700_004)
    service = _service(payment_db)
    invoice = await service.create_invoice(user.id, "reading_single")

    decisions = await asyncio.gather(
        *(
            service.validate_pre_checkout(
                700_004, f"query-{index}", invoice.payload, "XTR", invoice.amount
            )
            for index in range(6)
        )
    )
    replay = await service.validate_pre_checkout(
        700_004, "query-0", invoice.payload, "XTR", invoice.amount
    )

    assert sum(decision.approved for decision in decisions) == 1
    rejected = next(decision for decision in decisions if not decision.approved)
    assert rejected.error_message is not None and "оплачивается" in rejected.error_message
    async with payment_db() as session:
        order = await session.get(PaymentOrder, invoice.order_id)
        assert order is not None
        assert order.pre_checkout_authorized_at is not None
        # Telegram retries the same query when our answer is lost: that must stay idempotent.
        assert replay.approved == (order.pre_checkout_query_id == "query-0")


async def test_period_less_renewal_failure_applies_only_to_provider_managed_schedules(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """Stripe and YooKassa report a boundary, and their own path owns their past_due move."""
    # One active subscription per user and product, so each rail needs its own owner.
    stripe_owner = await _user(payment_db, 700_005)
    stars_owner = await _user(payment_db, 700_006)
    lifecycle = SubscriptionLifecycleService(payment_db)
    processor = SubscriptionEventProcessor(payment_db, lifecycle, grace_period_days=3)
    period_start = datetime(2026, 8, 1, tzinfo=UTC)
    period_end = datetime(2026, 9, 1, tzinfo=UTC)
    async with payment_db.begin() as session:
        for owner, provider, subscription_id in (
            (stripe_owner, "stripe", "sub_stripe"),
            (stars_owner, "telegram_stars", "stars-charge-initial"),
        ):
            customer = BillingCustomer(
                user_id=owner.id,
                provider=provider,
                provider_customer_id=f"customer-{provider}",
            )
            session.add(customer)
            await session.flush()
            session.add(
                Subscription(
                    user_id=owner.id,
                    billing_customer_id=customer.id,
                    provider=provider,
                    provider_subscription_id=subscription_id,
                    product_code="subscription_monthly",
                    product_version=1,
                    status="active",
                    current_period_start=period_start,
                    current_period_end=period_end,
                    consent_version="v1",
                    consented_at=period_start,
                )
            )

    def fact(
        owner: User, provider: str, subscription_id: str, status: str
    ) -> SubscriptionStateFact:
        return SubscriptionStateFact(
            user_id=owner.id,
            provider=provider,
            provider_subscription_id=subscription_id,
            status=status,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=False,
        )

    stripe_applied = await processor.apply(fact(stripe_owner, "stripe", "sub_stripe", "past_due"))
    stars_applied = await processor.apply(
        fact(stars_owner, "telegram_stars", "stars-charge-initial", "failed")
    )

    assert not stripe_applied
    assert stars_applied
    async with payment_db() as session:
        statuses = {
            value.provider: value.status
            for value in (await session.scalars(select(Subscription))).all()
        }
    assert statuses == {"stripe": "active", "telegram_stars": "past_due"}
