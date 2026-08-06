"""PostgreSQL invariants for catalog-v2 checkout migration."""

from uuid import uuid4

import pytest
from sqlalchemy import select
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


async def test_legacy_callback_creates_only_current_sku_and_immutable_label_snapshot(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with payment_db.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Catalog V2")
        session.add(user)
        await session.flush()
        user_id = user.id

    configured = settings.model_copy(
        update={
            "billing_enabled": True,
            "yookassa_enabled": True,
            "yookassa_receipts_required": False,
        }
    )
    gateway = RecordingGateway()
    service = CheckoutService(
        payment_db,
        configured,
        BillingCatalog(configured),
        {PaymentProviderName.YOOKASSA: gateway},
    )

    await service.create_one_time_checkout(
        user_id,
        "analysis_single",
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
