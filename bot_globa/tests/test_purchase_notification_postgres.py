"""A hosted-checkout buyer must be told, exactly once, that their payment landed."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PaymentOrder, User
from app.services.purchase_notification_service import (
    NotifierError,
    PurchaseNotificationWorker,
)
from tests.payment_postgres_helpers import create_order

pytestmark = pytest.mark.postgres


class RecordingNotifier:
    def __init__(self, failures: int = 0) -> None:
        self.sent: list[tuple[int, int]] = []
        self.failures = failures

    async def notify_purchase(self, telegram_user_id: int, readings: int) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise NotifierError("telegram unavailable")
        self.sent.append((telegram_user_id, readings))


async def _complete(
    sessions: async_sessionmaker[AsyncSession],
    order_id: UUID,
    *,
    credits: int = 1,
    completed_at: datetime | None = None,
) -> None:
    async with sessions.begin() as session:
        order = await session.get(PaymentOrder, order_id)
        assert order is not None
        order.status = "completed"
        order.credits = credits
        order.provider_payment_id = f"payment-{order.id}"
        order.completed_at = completed_at or datetime.now(UTC)


async def test_completed_order_notifies_the_buyer_exactly_once(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(payment_db, provider="yookassa")
    await _complete(payment_db, order_id, credits=5)
    notifier = RecordingNotifier()
    worker = PurchaseNotificationWorker(payment_db, notifier, reading_price_credits=1)

    assert await worker.run_once() is True
    assert await worker.run_once() is False
    assert await worker.run_once() is False

    async with payment_db() as session:
        order = await session.get(PaymentOrder, order_id)
        user = await session.get(User, user_id)
    assert order is not None and order.buyer_notified_at is not None
    assert user is not None and user.telegram_user_id is not None
    assert notifier.sent == [(user.telegram_user_id, 5)]


async def test_a_failed_send_is_retried_and_never_stamps_the_order(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    _, order_id = await create_order(payment_db, provider="yookassa")
    await _complete(payment_db, order_id)
    notifier = RecordingNotifier(failures=1)
    worker = PurchaseNotificationWorker(payment_db, notifier, reading_price_credits=1)

    assert await worker.run_once() is True
    async with payment_db() as session:
        order = await session.get(PaymentOrder, order_id)
    assert order is not None and order.buyer_notified_at is None
    assert notifier.sent == []

    assert await worker.run_once() is True
    async with payment_db() as session:
        order = await session.get(PaymentOrder, order_id)
    assert order is not None and order.buyer_notified_at is not None
    assert len(notifier.sent) == 1


async def test_credits_are_reported_as_readings_not_as_ledger_units(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    _, order_id = await create_order(payment_db, provider="yookassa")
    await _complete(payment_db, order_id, credits=15)
    notifier = RecordingNotifier()
    worker = PurchaseNotificationWorker(payment_db, notifier, reading_price_credits=5)

    assert await worker.run_once() is True
    assert [readings for _, readings in notifier.sent] == [3]


async def test_unpaid_deleted_and_stale_orders_are_never_notified(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    _, pending_order = await create_order(payment_db, provider="yookassa")

    deleted_user, deleted_order = await create_order(payment_db, provider="yookassa")
    await _complete(payment_db, deleted_order)
    async with payment_db.begin() as session:
        user = await session.get(User, deleted_user)
        assert user is not None
        user.privacy_status = "deleted"

    _, stale_order = await create_order(payment_db, provider="yookassa")
    await _complete(payment_db, stale_order, completed_at=datetime.now(UTC) - timedelta(days=3))

    _, stars_order = await create_order(payment_db, provider="telegram_stars")
    await _complete(payment_db, stars_order)

    notifier = RecordingNotifier()
    worker = PurchaseNotificationWorker(payment_db, notifier, reading_price_credits=1)

    assert await worker.run_once() is False
    assert notifier.sent == []
    async with payment_db() as session:
        for order_id in (pending_order, deleted_order, stale_order, stars_order):
            order = await session.get(PaymentOrder, order_id)
            assert order is not None and order.buyer_notified_at is None
