"""Financial lifecycle invariants for current catalog-v2 astrology products."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    CreditReservation,
    CreditTransaction,
    PaymentOrder,
    RefundRequest,
    User,
)
from app.domain.products import PRODUCT_CATALOG_VERSION
from app.providers.payments.gateway import AuthoritativePayment
from app.providers.payments.refund_gateway import (
    AuthoritativeRefund,
    CreateRefund,
    RefundCapabilities,
)
from app.services.payment_completion_service import PaymentCompletionService
from app.services.refund_service import RefundRequestOutcome, RefundService


class ReservationOnlyRefundGateway:
    refund_capabilities = RefundCapabilities(partial_refunds=True)

    async def create_refund(self, request: CreateRefund) -> AuthoritativeRefund:
        raise AssertionError(request)

    async def fetch_refund(self, refund_id: str) -> AuthoritativeRefund:
        raise AssertionError(refund_id)


async def test_astrology_v2_completion_and_refund_use_order_not_current_label(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with payment_db.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Astrology Billing")
        session.add(user)
        await session.flush()
        order = PaymentOrder(
            user_id=user.id,
            provider="stripe",
            product_code="astrology_natal",
            product_version=PRODUCT_CATALOG_VERSION,
            status="pending",
            credits=1,
            amount_minor=1_990,
            currency="EUR",
            market="INTERNATIONAL",
            mode="one_time",
            provider_checkout_id="checkout-astrology-v2",
            provider_status="open",
            idempotency_key=f"checkout:create:{uuid4()}:v1",
            commercial_snapshot={
                "product_code": "astrology_natal",
                "product_version": PRODUCT_CATALOG_VERSION,
                "title": "Historical title frozen at checkout",
                "receipt_label": "Historical receipt label frozen at checkout",
                "credits": 1,
                "amount_minor": 1_990,
                "currency": "EUR",
                "provider": "stripe",
                "market": "INTERNATIONAL",
                "price_reference": "price-approved-single-eur",
                "billing_period": None,
            },
        )
        session.add(order)
        await session.flush()
        user_id, order_id = user.id, order.id

    outcome = await PaymentCompletionService(payment_db).complete(
        order_id,
        AuthoritativePayment(
            checkout_id="checkout-astrology-v2",
            payment_id="payment-astrology-v2",
            status="succeeded",
            amount_minor=1_990,
            currency="EUR",
            order_id=str(order_id),
            mode="payment",
            paid=True,
            live_mode=False,
            provider_status="paid",
        ),
    )
    assert outcome == "completed"

    configured = settings.model_copy(
        update={
            "billing_enabled": True,
            "refunds_enabled": True,
            "stripe_enabled": True,
            "billing_refund_window_days": 14,
        }
    )
    refund = await RefundService(
        payment_db,
        configured,
        {"stripe": ReservationOnlyRefundGateway()},
    ).request_refund(user_id, order_id)

    assert refund.outcome is RefundRequestOutcome.CREATED
    assert refund.refund is not None
    assert refund.refund.amount_minor == 1_990
    assert refund.refund.credit_units == 1

    async with payment_db() as session:
        stored_order = await session.get(PaymentOrder, order_id)
        purchase = await session.scalar(
            select(CreditTransaction).where(
                CreditTransaction.payment_order_id == order_id,
                CreditTransaction.type == "purchase",
            )
        )
        request = await session.scalar(
            select(RefundRequest).where(RefundRequest.payment_order_id == order_id)
        )
        assert request is not None
        reservation = await session.scalar(
            select(CreditReservation).where(CreditReservation.refund_request_id == request.id)
        )

    assert stored_order is not None and stored_order.status == "completed"
    assert stored_order.completed_at is not None
    assert stored_order.completed_at <= datetime.now(UTC)
    assert purchase is not None
    assert purchase.product_code == "astrology_natal"
    assert purchase.amount == 1
    assert request.amount_minor == stored_order.amount_minor
    assert request.currency == stored_order.currency
    assert reservation is not None and reservation.credit_units == stored_order.credits
