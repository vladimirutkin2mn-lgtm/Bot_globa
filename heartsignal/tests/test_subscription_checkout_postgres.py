import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import BillingJob, PaymentOrder, User
from app.domain.billing import BillingCatalog
from app.domain.products import PRODUCT_CATALOG_VERSION
from app.providers.payments.base import PaymentProviderName, UnknownProviderOutcome
from app.providers.payments.subscription_gateway import (
    CreateSubscriptionCheckout,
    HostedSubscriptionCheckout,
    SubscriptionProviderFact,
    SubscriptionStateFact,
)
from app.services.subscription_checkout_service import SubscriptionCheckoutService
from tests.payment_postgres_helpers import payment_db  # noqa: F401

pytestmark = pytest.mark.postgres


class FakeSubscriptionGateway:
    def __init__(self, *, unknown: bool = False) -> None:
        self.unknown = unknown
        self.calls: list[CreateSubscriptionCheckout] = []

    async def create_subscription_checkout(
        self, request: CreateSubscriptionCheckout
    ) -> HostedSubscriptionCheckout:
        self.calls.append(request)
        await asyncio.sleep(0.02)
        if self.unknown:
            raise UnknownProviderOutcome
        return HostedSubscriptionCheckout(
            checkout_id="cs_subscription_one",
            url="https://provider.test/subscription",
            status="open",
            expires_at=datetime.now(UTC),
            live_mode=False,
        )

    async def fetch_subscription_event(
        self, event_type: str, object_id: str
    ) -> SubscriptionProviderFact:
        raise AssertionError((event_type, object_id))

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionProviderFact:
        raise AssertionError(subscription_id)

    async def cancel_subscription(self, subscription_id: str) -> SubscriptionStateFact:
        raise AssertionError(subscription_id)

    async def resume_subscription(self, subscription_id: str) -> SubscriptionStateFact:
        raise AssertionError(subscription_id)


def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://u:p@db/x",
        telegram_bot_token=SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        content_encryption_key=SecretStr("test-only-strong-content-key-32-bytes"),
        billing_enabled=True,
        payment_provider="production",
        payment_public_base_url="https://pay.example",
        subscriptions_enabled=True,
        stripe_price_subscription_monthly_eur="price_monthly_eur",
        stripe_amount_subscription_monthly_eur_minor=990,
        product_subscription_monthly_credits=30,
        checkout_creation_lease_seconds=1,
    )


async def create_user(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    async with sessions.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Subscription")
        session.add(user)
        await session.flush()
        return user.id


@pytest.mark.asyncio
async def test_concurrent_subscription_checkout_has_one_provider_owner(
    payment_db: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    gateway = FakeSubscriptionGateway()
    configured = settings()
    service = SubscriptionCheckoutService(
        payment_db,
        configured,
        BillingCatalog(configured),
        {PaymentProviderName.STRIPE: gateway},
    )
    user_id = await create_user(payment_db)

    results = await asyncio.gather(
        *(
            service.create_checkout(
                user_id,
                "subscription_monthly",
                "INTERNATIONAL",
                "EUR",
            )
            for _ in range(10)
        )
    )

    assert len(gateway.calls) == 1
    assert len({result.order_id for result in results}) == 1
    existing = await service.create_checkout(
        user_id,
        "subscription_monthly",
        "INTERNATIONAL",
        "EUR",
    )
    assert existing.url == "https://provider.test/subscription"
    async with payment_db() as session:
        order = await session.scalar(select(PaymentOrder))
        assert order is not None
        assert order.mode == "subscription_initial"
        assert order.product_version == PRODUCT_CATALOG_VERSION
        assert order.amount_minor == 990
        assert order.credits == 30
        assert order.commercial_snapshot["consent_version"] == "billing-v1"
        assert order.commercial_snapshot["receipt_label"] == (
            "Месячная подписка персонального AI-оракула"
        )
        assert await session.scalar(select(func.count()).select_from(PaymentOrder)) == 1


@pytest.mark.asyncio
async def test_current_subscription_replays_unfinished_v1_snapshot_without_repricing(
    payment_db: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    user_id = await create_user(payment_db)
    async with payment_db.begin() as session:
        order = PaymentOrder(
            user_id=user_id,
            provider="stripe",
            product_code="subscription_monthly",
            product_version=1,
            status="creating",
            credits=9,
            amount_minor=777,
            currency="EUR",
            market="INTERNATIONAL",
            mode="subscription_initial",
            billing_period="month",
            idempotency_key=f"subscription:checkout:{uuid4()}:v1",
            checkout_creation_started_at=datetime.now(UTC) - timedelta(minutes=5),
            commercial_snapshot={
                "product_code": "subscription_monthly",
                "product_version": 1,
                "title": "Legacy subscription",
                "receipt_label": "Legacy subscription receipt",
                "credits": 9,
                "amount_minor": 777,
                "currency": "EUR",
                "provider": "stripe",
                "market": "INTERNATIONAL",
                "price_reference": "price_legacy_monthly_eur",
                "billing_period": "month",
                "consent_version": "billing-v0",
            },
        )
        session.add(order)
        await session.flush()
        order_id = order.id

    gateway = FakeSubscriptionGateway()
    configured = settings()
    result = await SubscriptionCheckoutService(
        payment_db,
        configured,
        BillingCatalog(configured),
        {PaymentProviderName.STRIPE: gateway},
    ).create_checkout(
        user_id,
        "subscription_monthly",
        "INTERNATIONAL",
        "EUR",
    )

    async with payment_db() as session:
        count = await session.scalar(select(func.count()).select_from(PaymentOrder))
        stored = await session.get(PaymentOrder, order_id)
    assert result.order_id == order_id
    assert count == 1
    assert stored is not None and stored.status == "pending"
    assert len(gateway.calls) == 1
    request = gateway.calls[0]
    assert request.product_version == 1
    assert request.credits == 9
    assert request.amount_minor == 777
    assert request.price_reference == "price_legacy_monthly_eur"
    assert request.consent_version == "billing-v0"
    assert request.receipt_label == "Legacy subscription receipt"


@pytest.mark.asyncio
async def test_unknown_checkout_creates_one_durable_reconciliation_job(
    payment_db: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    gateway = FakeSubscriptionGateway(unknown=True)
    configured = settings()
    service = SubscriptionCheckoutService(
        payment_db,
        configured,
        BillingCatalog(configured),
        {PaymentProviderName.STRIPE: gateway},
    )
    user_id = await create_user(payment_db)

    first = await service.create_checkout(
        user_id,
        "subscription_monthly",
        "INTERNATIONAL",
        "EUR",
    )
    second = await service.create_checkout(
        user_id,
        "subscription_monthly",
        "INTERNATIONAL",
        "EUR",
    )

    assert first.order_id == second.order_id
    assert len(gateway.calls) == 1
    async with payment_db() as session:
        job = await session.scalar(select(BillingJob))
        assert job is not None
        assert job.job_type == "subscription_checkout_reconcile"
        assert await session.scalar(select(func.count()).select_from(BillingJob)) == 1
