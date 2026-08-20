"""User-facing payment status lookup and authoritative reconciliation trigger."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PaymentOrder
from app.providers.payments.base import PaymentProviderError
from app.providers.payments.gateway import OneTimePaymentGateway
from app.services.payment_completion_service import PaymentCompletionService
from app.services.payment_reconciliation_service import PaymentReconciliationSweeper

logger = logging.getLogger(__name__)
_MAX_DIRECT_RECONCILIATIONS = 5


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
    """Expose the user's payment state and recover open hosted checkouts safely."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        pending_seconds: int,
        gateways: dict[str, OneTimePaymentGateway] | None = None,
        completion: PaymentCompletionService | None = None,
    ) -> None:
        self._sessions = sessions
        self._gateways = gateways or {}
        self._completion = completion
        supported = set(self._gateways) if self._gateways else None
        self._sweeper = PaymentReconciliationSweeper(sessions, pending_seconds, supported)

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
        """Authoritatively reconcile recent open payments, then wake durable fallback jobs.

        A Telegram callback is never treated as proof of payment. When a configured
        provider gateway is available, refresh asks that provider directly and sends the
        normalized result through the same exactly-once PaymentCompletionService used by
        background jobs. Durable reconciliation is still woken afterwards as a fallback.
        """

        open_orders = await self._open_orders(user_id)
        if not open_orders:
            return await self.latest(user_id)

        direct_results = await asyncio.gather(
            *(self._reconcile_direct(order) for order in open_orders)
        )
        requested = any(direct_results)
        for order in open_orders:
            requested = await self._sweeper.enqueue_order(order.id, wake_existing=True) or requested

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

    async def _open_orders(self, user_id: UUID) -> list[PaymentOrder]:
        async with self._sessions() as session:
            return list(
                await session.scalars(
                    select(PaymentOrder)
                    .where(
                        PaymentOrder.user_id == user_id,
                        PaymentOrder.mode == "one_time",
                        PaymentOrder.status.in_(("creating", "pending")),
                    )
                    .order_by(PaymentOrder.created_at.desc())
                    .limit(_MAX_DIRECT_RECONCILIATIONS)
                )
            )

    async def _reconcile_direct(self, order: PaymentOrder) -> bool:
        checkout_id = order.provider_checkout_id
        gateway = self._gateways.get(order.provider)
        if checkout_id is None or gateway is None or self._completion is None:
            return False
        try:
            payment = await gateway.fetch_payment(checkout_id)
        except PaymentProviderError as exc:
            logger.warning(
                "payment_status_direct_reconciliation_provider_error "
                "provider=%s order_id=%s error=%s",
                order.provider,
                order.id,
                type(exc).__name__,
            )
            return False
        await self._completion.complete(order.id, payment)
        return True

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
