"""User-facing payment status lookup and authoritative reconciliation trigger."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PaymentOrder
from app.services.payment_reconciliation_service import PaymentReconciliationSweeper


@dataclass(frozen=True, slots=True)
class PaymentStatusView:
    order_id: UUID
    provider: str
    product_code: str
    status: str
    failure_code: str | None
    created_at: datetime
    reconciliation_requested: bool = False


class PaymentStatusService:
    """Expose only the current user's own payment state and wake safe reconciliation."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        pending_seconds: int,
    ) -> None:
        self._sessions = sessions
        self._sweeper = PaymentReconciliationSweeper(sessions, pending_seconds)

    async def latest(self, user_id: UUID) -> PaymentStatusView | None:
        async with self._sessions() as session:
            order = await session.scalar(
                select(PaymentOrder)
                .where(
                    PaymentOrder.user_id == user_id,
                    PaymentOrder.mode == "one_time",
                )
                .order_by(PaymentOrder.created_at.desc())
                .limit(1)
            )
            return self._view(order) if order is not None else None

    async def refresh(self, user_id: UUID) -> PaymentStatusView | None:
        """Wake provider reconciliation for the user's latest open hosted checkout.

        The browser/user action is never treated as payment proof. Credit can only be
        granted later by PaymentCompletionService after the provider reports succeeded.
        """

        latest = await self.latest(user_id)
        if latest is None or latest.status not in {"creating", "pending"}:
            return latest
        requested = await self._sweeper.enqueue_order(latest.order_id, wake_existing=True)
        current = await self.latest(user_id)
        if current is None:
            return None
        return PaymentStatusView(
            order_id=current.order_id,
            provider=current.provider,
            product_code=current.product_code,
            status=current.status,
            failure_code=current.failure_code,
            created_at=current.created_at,
            reconciliation_requested=requested,
        )

    @staticmethod
    def _view(order: PaymentOrder) -> PaymentStatusView:
        return PaymentStatusView(
            order_id=order.id,
            provider=order.provider,
            product_code=order.product_code,
            status=order.status,
            failure_code=order.failure_code,
            created_at=order.created_at,
        )
