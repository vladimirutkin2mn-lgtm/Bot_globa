"""PostgreSQL invariants for catalog-v2 checkout migration."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import PaymentOrder, User
from app.domain.billing import BillingCatalog
from app.domain.products import PRODUCT_CATALOG_VERSION
from app.providers.payments.base import PaymentProviderName
from app.providers.payments.gateway import CreateCheckout, HostedCheckout
from app.services.checkout_service import CheckoutService

pytestmark = pytest.mark.postgres


class RecordingGateway:
    def __init__(self) -> None:
        self.requests: list[CreateCheckout] = []

    async def create_checkout(self, request: CreateCheckout) -> HostedCheckout:
        self.requests.append(request)
        return HostedCheckout(
            checkout_id=f"payment-{len(self.requests)}",
            url="https://provider.test/catalog-v2",
            status="pending",
            live_mode=False,
        )

    async def fetch_payment(self, checkout_id: str):  # type: ignore[no-untyped-def]
        raise AssertionError(checkout_id)


def _configured(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "billing_enabled": True,
            "yookassa_enabled": True,
            "yookassa_receipts_required": False,
            "checkout_creation_lease_seconds": 1,
        }
    )


async def test_checkout_creates_the_current_sku_with_an_immutable_label_snapshot(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with payment_db.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Catalog V2")
        session.add(user)
        await session.flush()
        user_id = user.id

    configured = _configured(settings)
    gateway = RecordingGateway()
    service = CheckoutService(
        payment_db,
        configured,
        BillingCatalog(configured),
        {PaymentProviderName.YOOKASSA: gateway},
    )

    await service.create_one_time_checkout(
        user_id,
        "reading_single",
        "RU",
        "RUB",
    )

    async with payment_db() as session:
        order = await session.scalar(select(PaymentOrder).where(PaymentOrder.user_id == user_id))
    assert order is not None
    assert order.product_code == "reading_single"
    assert order.product_version == PRODUCT_CATALOG_VERSION
    assert order.commercial_snapshot["product_code"] == "reading_single"
    assert order.commercial_snapshot["product_version"] == PRODUCT_CATALOG_VERSION
    assert order.commercial_snapshot["title"] == "Один полный разбор"
    assert order.commercial_snapshot["receipt_label"] == "Полный персональный разбор"
    assert len(gateway.requests) == 1
    assert gateway.requests[0].product_code == "reading_single"
    assert gateway.requests[0].receipt_label == "Полный персональный разбор"


async def test_current_callback_replays_unfinished_v1_order_without_catalog_repricing(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with payment_db.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Legacy Pending")
        session.add(user)
        await session.flush()
        order = PaymentOrder(
            user_id=user.id,
            provider="yookassa",
            product_code="reading_single",
            product_version=1,
            status="creating",
            credits=7,
            amount_minor=12_345,
            currency="RUB",
            market="RU",
            mode="one_time",
            idempotency_key=f"checkout:create:{uuid4()}:v1",
            checkout_creation_started_at=datetime.now(UTC) - timedelta(minutes=5),
            commercial_snapshot={
                "product_code": "reading_single",
                "product_version": 1,
                "title": "Legacy frozen title",
                "receipt_label": "Legacy frozen receipt label",
                "credits": 7,
                "amount_minor": 12_345,
                "currency": "RUB",
                "provider": "yookassa",
                "market": "RU",
                "price_reference": "catalog:reading_single:rub:v1",
                "billing_period": None,
            },
        )
        session.add(order)
        await session.flush()
        user_id, order_id = user.id, order.id

    configured = _configured(settings)
    gateway = RecordingGateway()
    service = CheckoutService(
        payment_db,
        configured,
        BillingCatalog(configured),
        {PaymentProviderName.YOOKASSA: gateway},
    )

    result = await service.create_one_time_checkout(
        user_id,
        "reading_single",
        "RU",
        "RUB",
    )

    async with payment_db() as session:
        count = await session.scalar(
            select(func.count()).select_from(PaymentOrder).where(PaymentOrder.user_id == user_id)
        )
        stored = await session.get(PaymentOrder, order_id)
    assert result.order_id == order_id
    assert count == 1
    assert stored is not None and stored.status == "pending"
    assert stored.product_code == "reading_single"
    assert stored.product_version == 1
    assert len(gateway.requests) == 1
    request = gateway.requests[0]
    assert request.product_code == "reading_single"
    assert request.product_version == 1
    assert request.amount_minor == 12_345
    assert request.price_reference == "catalog:reading_single:rub:v1"
    assert request.receipt_label == "Legacy frozen receipt label"
