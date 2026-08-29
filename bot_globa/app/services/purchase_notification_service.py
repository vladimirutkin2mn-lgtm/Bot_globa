"""Tell the buyer, inside the bot, that a hosted checkout actually landed.

Telegram Stars completes inside a bot handler, so the buyer sees the outcome immediately.
A YooKassa or Stripe checkout does not: the buyer leaves for a payment page — often
finishing inside a banking app that never returns to the browser — and the order is
completed later by the billing worker. Without this worker nothing in Telegram ever changes,
and a paid reading is indistinguishable from a failed payment.

The message carries no reading content and no financial detail beyond the entitlement that
was granted: it says the payment arrived and offers the screen that opens the reading.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PaymentOrder, User

logger = logging.getLogger(__name__)

PROVIDER_HOSTED_CHECKOUT = ("stripe", "yookassa")


class NotifierError(RuntimeError):
    """A delivery attempt failed; the order stays unstamped and is retried."""


class BuyerNotifier(Protocol):
    async def notify_purchase(self, telegram_user_id: int, readings: int) -> None:
        """Send the completion notice, or raise `NotifierError`."""
        ...


class PurchaseNotificationWorker:
    """Deliver one completion notice per completed order, at least once.

    The row is held with `FOR UPDATE SKIP LOCKED` across the send, so two workers can never
    notify the same buyer twice, and the stamp commits with the lock. A crash mid-send rolls
    the stamp back and the next tick retries: a repeated "payment received" is a far smaller
    failure than silence about a reading someone paid for. Only recent completions are
    considered, so a Telegram outage cannot leave the worker retrying an old order forever.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        notifier: BuyerNotifier,
        reading_price_credits: int,
        max_age: timedelta = timedelta(days=1),
    ) -> None:
        if reading_price_credits < 1:
            raise ValueError("reading price must be positive")
        self._sessions = sessions
        self._notifier = notifier
        self._price = reading_price_credits
        self._max_age = max_age

    async def run_once(self) -> bool:
        cutoff = datetime.now(UTC) - self._max_age
        try:
            async with self._sessions.begin() as session:
                claimed = await self._claim(session, cutoff)
                if claimed is None:
                    return False
                order, telegram_user_id = claimed
                readings = max(order.credits // self._price, 1)
                await self._notifier.notify_purchase(telegram_user_id, readings)
                order.buyer_notified_at = datetime.now(UTC)
        except NotifierError:
            # The stamp rolled back with the failed send; the next tick retries this order.
            logger.warning("purchase_notification_failed", exc_info=True)
        return True

    @staticmethod
    async def _claim(session: AsyncSession, cutoff: datetime) -> tuple[PaymentOrder, int] | None:
        row = (
            await session.execute(
                select(PaymentOrder, User.telegram_user_id)
                .join(User, User.id == PaymentOrder.user_id)
                .where(
                    PaymentOrder.status == "completed",
                    PaymentOrder.buyer_notified_at.is_(None),
                    PaymentOrder.completed_at.is_not(None),
                    PaymentOrder.completed_at >= cutoff,
                    PaymentOrder.provider.in_(PROVIDER_HOSTED_CHECKOUT),
                    User.privacy_status == "active",
                    User.telegram_user_id.is_not(None),
                )
                .order_by(PaymentOrder.completed_at)
                .with_for_update(skip_locked=True, of=PaymentOrder)
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        order, telegram_user_id = row
        assert telegram_user_id is not None
        return order, telegram_user_id
