"""YooKassa renewal keeps the catalog label after lifecycle-created renewal orders."""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import PaymentOrder, Subscription, User
from app.providers.payments.subscription_gateway import (
    PaidSubscriptionFact,
    RenewSubscription,
    SubscriptionProviderFact,
    SubscriptionStateFact,
)
from app.providers.payments.yookassa_gateway import YooKassaGateway
from app.providers.payments.yookassa_subscription_gateway import (
    YooKassaSubscriptionGateway,
)
from app.services.subscription_event_processor import SubscriptionEventProcessor
from app.services.subscription_lifecycle import SubscriptionLifecycleService
from tests.payment_postgres_helpers import payment_db  # noqa: F401


class RecordingYooKassaGateway:
    def __init__(self) -> None:
        self.renewal: RenewSubscription | None = None

    async def renew_subscription(self, request: RenewSubscription) -> SubscriptionProviderFact:
        self.renewal = request
        return SubscriptionStateFact(
            user_id=request.user_id,
            provider="yookassa",
            provider_subscription_id=request.provider_subscription_id,
            status="active",
            current_period_start=request.period_start,
            current_period_end=request.period_end,
            cancel_at_period_end=False,
        )


async def _initial_order(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    async with sessions.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Renewal Label")
        session.add(user)
        await session.flush()
        order = PaymentOrder(
            user_id=user.id,
            provider="yookassa",
            product_code="subscription_monthly",
            product_version=2,
            status="pending",
            credits=30,
            amount_minor=99_000,
            currency="RUB",
            market="RU",
            mode="subscription_initial",
            billing_period="month",
            provider_checkout_id="payment-label-initial",
            provider_status="pending",
            idempotency_key=f"subscription:checkout:{uuid4()}:v1",
            commercial_snapshot={
                "product_code": "subscription_monthly",
                "product_version": 2,
                "title": "Месячная подписка",
                "receipt_label": "Месячная подписка персонального AI-оракула",
                "credits": 30,
                "amount_minor": 99_000,
                "currency": "RUB",
                "provider": "yookassa",
                "market": "RU",
                "price_reference": "catalog:subscription_monthly:rub:v2",
                "billing_period": "month",
                "consent_version": "billing-v1",
            },
        )
        session.add(order)
        await session.flush()
        return user.id, order.id


def _fact(
    user_id: UUID,
    *,
    order_id: UUID | None,
    subscription_id: str,
    invoice_id: str,
    payment_id: str,
    period_start: datetime,
    period_end: datetime,
    amount_minor: int,
    credits: int,
    price_reference: str,
    encrypted_payment_method: bytes | None = None,
) -> PaidSubscriptionFact:
    return PaidSubscriptionFact(
        user_id=user_id,
        initial_order_id=order_id,
        provider="yookassa",
        provider_customer_id=f"yookassa:{user_id}",
        provider_subscription_id=subscription_id,
        provider_invoice_id=invoice_id,
        provider_payment_id=payment_id,
        product_code="subscription_monthly",
        product_version=2,
        market="RU",
        currency="RUB",
        amount_minor=amount_minor,
        credits=credits,
        price_reference=price_reference,
        period_start=period_start,
        period_end=period_end,
        paid_at=period_start + timedelta(minutes=1),
        consent_version="billing-v1",
        live_mode=False,
        encrypted_payment_method=encrypted_payment_method,
    )


async def test_later_renewal_uses_latest_terms_and_initial_receipt_label(
    payment_db: async_sessionmaker[AsyncSession],  # noqa: F811
    settings: Settings,
) -> None:
    user_id, order_id = await _initial_order(payment_db)
    now = datetime.now(UTC)
    initial_start = now - timedelta(days=62)
    initial_end = now - timedelta(days=32)
    renewal_end = now - timedelta(days=1)
    provider_subscription_id = f"yookassa:{order_id}"
    processor = SubscriptionEventProcessor(
        payment_db,
        SubscriptionLifecycleService(payment_db),
        grace_period_days=3,
    )

    await processor.apply(
        _fact(
            user_id,
            order_id=order_id,
            subscription_id=provider_subscription_id,
            invoice_id="invoice-label-initial",
            payment_id="payment-label-initial",
            period_start=initial_start,
            period_end=initial_end,
            amount_minor=99_000,
            credits=30,
            price_reference="catalog:subscription_monthly:rub:v2",
            encrypted_payment_method=b"authenticated-payment-method",
        )
    )
    await processor.apply(
        _fact(
            user_id,
            order_id=None,
            subscription_id=provider_subscription_id,
            invoice_id="invoice-label-renewal",
            payment_id="payment-label-renewal",
            period_start=initial_end,
            period_end=renewal_end,
            amount_minor=88_000,
            credits=25,
            price_reference="catalog:subscription_monthly:rub:v2-renewal",
        )
    )

    async with payment_db() as session:
        subscription = await session.scalar(select(Subscription))
        assert subscription is not None and subscription.last_order_id is not None
        last_order = await session.get(PaymentOrder, subscription.last_order_id)
        assert last_order is not None
        assert "receipt_label" not in last_order.commercial_snapshot

    recording = RecordingYooKassaGateway()
    configured = settings.model_copy(
        update={"yookassa_receipt_email": "receipt@example.com"}
    )
    gateway = YooKassaSubscriptionGateway(
        payment_db,
        configured,
        cast(YooKassaGateway, recording),
    )

    await gateway.fetch_subscription(provider_subscription_id)

    request = recording.renewal
    assert request is not None
    assert request.amount_minor == 88_000
    assert request.credits == 25
    assert request.price_reference == "catalog:subscription_monthly:rub:v2-renewal"
    assert request.receipt_label == "Месячная подписка персонального AI-оракула"
