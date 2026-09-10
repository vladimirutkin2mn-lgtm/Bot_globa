"""A hosted-checkout buyer must be told, exactly once, that their payment landed."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PaymentOrder, User
from app.db.reading_models import Persona, Reading
from app.domain.reading_checkout_resume import ReadingCheckoutTarget
from app.services.purchase_notification_service import (
    NotifierError,
    PurchaseNotificationWorker,
)
from tests.payment_postgres_helpers import create_order

pytestmark = pytest.mark.postgres


class RecordingNotifier:
    def __init__(self, failures: int = 0) -> None:
        self.sent: list[tuple[int, int, str | None]] = []
        self.failures = failures

    async def notify_purchase(
        self,
        telegram_user_id: int,
        readings: int,
        resume_callback: str | None = None,
    ) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise NotifierError("telegram unavailable")
        self.sent.append((telegram_user_id, readings, resume_callback))


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


async def _ready_reading(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    *,
    persona_code: str = "tarot_reader",
) -> Reading:
    async with sessions.begin() as session:
        persona = await session.scalar(select(Persona).where(Persona.code == persona_code))
        if persona is None:
            persona = Persona(
                code=persona_code,
                display_name="Test persona",
                prompt_version="test-v1",
                schema_version="reading-result-v1",
            )
            session.add(persona)
            await session.flush()
        reading = Reading(
            user_id=user_id,
            persona_id=persona.id,
            topic="decision",
            status="preview_ready",
            access_level="preview",
            engine_version="test-v1",
            prompt_version="test-v1",
            schema_version="reading-result-v1",
            symbol_set_code="none",
            generated_at=datetime.now(UTC),
        )
        session.add(reading)
        await session.flush()
        return reading


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
    assert notifier.sent == [(user.telegram_user_id, 5, None)]


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
    assert [readings for _, readings, _ in notifier.sent] == [3]


async def test_completed_targeted_order_returns_to_the_exact_authorized_reading(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(payment_db, provider="stripe")
    reading = await _ready_reading(payment_db, user_id, persona_code="love_oracle")
    target = ReadingCheckoutTarget(reading.id, "love_oracle")
    async with payment_db.begin() as session:
        order = await session.get(PaymentOrder, order_id)
        assert order is not None
        order.commercial_snapshot = {
            **order.commercial_snapshot,
            "resume_target": target.snapshot(),
        }
    await _complete(payment_db, order_id)
    notifier = RecordingNotifier()
    worker = PurchaseNotificationWorker(payment_db, notifier, reading_price_credits=1)

    assert await worker.run_once() is True

    async with payment_db() as session:
        user = await session.get(User, user_id)
    assert user is not None and user.telegram_user_id is not None
    assert notifier.sent == [(user.telegram_user_id, 1, f"love:unlock:{reading.id}")]


async def test_foreign_or_malformed_resume_target_falls_back_without_exposing_a_reading(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(payment_db, provider="yookassa")
    async with payment_db.begin() as session:
        other = User(telegram_user_id=88776655, first_name="Other")
        session.add(other)
        await session.flush()
        other_id = other.id
    foreign = await _ready_reading(payment_db, other_id)
    target = ReadingCheckoutTarget(foreign.id, "tarot_reader")
    async with payment_db.begin() as session:
        order = await session.get(PaymentOrder, order_id)
        assert order is not None
        order.commercial_snapshot = {
            **order.commercial_snapshot,
            "resume_target": target.snapshot(),
        }
    await _complete(payment_db, order_id)
    notifier = RecordingNotifier()
    worker = PurchaseNotificationWorker(payment_db, notifier, reading_price_credits=1)

    assert await worker.run_once() is True

    async with payment_db() as session:
        user = await session.get(User, user_id)
    assert user is not None and user.telegram_user_id is not None
    assert notifier.sent == [(user.telegram_user_id, 1, None)]


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
