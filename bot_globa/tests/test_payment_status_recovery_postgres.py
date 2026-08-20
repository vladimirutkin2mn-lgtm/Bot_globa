"""Production-shaped recovery checks for the user-facing payment refresh path."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BillingJob, CreditTransaction, PaymentOrder
from app.providers.payments.gateway import AuthoritativePayment, CreateCheckout, HostedCheckout
from app.services.payment_completion_service import PaymentCompletionService
from app.services.payment_status_service import PaymentStatusService
from tests.payment_postgres_helpers import create_order, paid

pytestmark = pytest.mark.postgres


class _MultiPaymentGateway:
    def __init__(self, payments: dict[str, AuthoritativePayment]) -> None:
        self._payments = payments
        self.fetches: list[str] = []

    async def create_checkout(self, request: CreateCheckout) -> HostedCheckout:
        raise AssertionError(f"unexpected checkout creation: {request.order_id}")

    async def fetch_payment(self, checkout_id: str) -> AuthoritativePayment:
        self.fetches.append(checkout_id)
        return self._payments[checkout_id]


async def test_user_refresh_enqueues_latest_pending_yookassa_order_once(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(
        payment_db,
        provider="yookassa",
        checkout_id="user-refresh-yookassa",
    )
    service = PaymentStatusService(payment_db, 60)

    first = await service.refresh(user_id)

    assert first is not None
    assert first.order_id == order_id
    assert first.status == "pending"
    assert first.reconciliation_requested
    async with payment_db() as session:
        jobs = await session.scalar(select(func.count()).select_from(BillingJob))
        job = await session.scalar(select(BillingJob))
    assert jobs == 1
    assert job is not None
    assert job.job_type == "payment_reconciliation"
    assert job.object_id == str(order_id)


async def test_user_refresh_recovers_failed_and_pending_paid_yookassa_orders(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, first_order_id = await create_order(
        payment_db,
        provider="yookassa",
        checkout_id="first-real-payment",
    )
    second_order_id = uuid4()
    async with payment_db.begin() as session:
        first_order = await session.get(PaymentOrder, first_order_id, with_for_update=True)
        assert first_order is not None
        first_order.status = "failed"
        first_order.failure_code = "provider_timeout"
        await session.flush()
        session.add(
            PaymentOrder(
                id=second_order_id,
                user_id=user_id,
                provider="yookassa",
                product_code=first_order.product_code,
                status="pending",
                credits=first_order.credits,
                amount_minor=first_order.amount_minor,
                currency=first_order.currency,
                market=first_order.market,
                mode="one_time",
                product_version=first_order.product_version,
                provider_checkout_id="second-real-payment",
                idempotency_key=f"checkout:create:{uuid4()}:v1",
                commercial_snapshot=dict(first_order.commercial_snapshot),
            )
        )

    gateway = _MultiPaymentGateway(
        {
            "first-real-payment": paid(
                first_order_id,
                "first-real-payment",
                "provider-payment-one",
            ),
            "second-real-payment": paid(
                second_order_id,
                "second-real-payment",
                "provider-payment-two",
            ),
        }
    )
    service = PaymentStatusService(
        payment_db,
        60,
        {"yookassa": gateway},
        PaymentCompletionService(payment_db),
    )

    status = await service.refresh(user_id)

    assert status is not None
    assert status.status == "completed"
    assert status.reconciliation_requested
    assert set(gateway.fetches) == {"first-real-payment", "second-real-payment"}
    async with payment_db() as session:
        orders = list(
            await session.scalars(select(PaymentOrder).where(PaymentOrder.user_id == user_id))
        )
        purchases = await session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(
                CreditTransaction.user_id == user_id,
                CreditTransaction.type == "purchase",
            )
        )
        jobs = await session.scalar(select(func.count()).select_from(BillingJob))
    assert {order.status for order in orders} == {"completed"}
    assert all(order.failure_code is None for order in orders)
    assert purchases == 2
    assert jobs == 0


async def test_user_refresh_wakes_existing_delayed_retry_without_resetting_budget(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(
        payment_db,
        provider="yookassa",
        checkout_id="delayed-retry-yookassa",
    )
    service = PaymentStatusService(payment_db, 60)
    first = await service.refresh(user_id)
    assert first is not None and first.reconciliation_requested

    delayed_until = datetime.now(UTC) + timedelta(minutes=10)
    async with payment_db.begin() as session:
        job = await session.scalar(select(BillingJob).where(BillingJob.object_id == str(order_id)))
        assert job is not None
        job.available_at = delayed_until
        job.attempt_count = 3
        job.last_error_code = "provider_timeout"

    before_refresh = datetime.now(UTC)
    second = await service.refresh(user_id)

    assert second is not None and second.reconciliation_requested
    async with payment_db() as session:
        job = await session.scalar(select(BillingJob).where(BillingJob.object_id == str(order_id)))
    assert job is not None
    assert job.status == "pending"
    assert job.available_at >= before_refresh
    assert job.available_at < delayed_until
    assert job.attempt_count == 3
    assert job.last_error_code == "provider_timeout"


async def test_user_refresh_does_not_steal_active_reconciliation_lease(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(
        payment_db,
        provider="yookassa",
        checkout_id="active-lease-yookassa",
    )
    claim_id = uuid4()
    lease_until = datetime.now(UTC) + timedelta(minutes=5)
    async with payment_db.begin() as session:
        session.add(
            BillingJob(
                job_type="payment_reconciliation",
                provider="yookassa",
                object_type="payment_order",
                object_id=str(order_id),
                idempotency_key=f"reconcile:{order_id}",
                status="claimed",
                attempt_count=2,
                claimed_by="billing-worker-live",
                claim_id=claim_id,
                claimed_at=datetime.now(UTC),
                lease_until=lease_until,
            )
        )

    status = await PaymentStatusService(payment_db, 60).refresh(user_id)

    assert status is not None and not status.reconciliation_requested
    async with payment_db() as session:
        job = await session.scalar(select(BillingJob).where(BillingJob.object_id == str(order_id)))
    assert job is not None
    assert job.status == "claimed"
    assert job.claim_id == claim_id
    assert job.claimed_by == "billing-worker-live"
    assert job.lease_until == lease_until
    assert job.attempt_count == 2


async def test_user_refresh_recovers_expired_reconciliation_lease(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(
        payment_db,
        provider="yookassa",
        checkout_id="expired-lease-yookassa",
    )
    async with payment_db.begin() as session:
        session.add(
            BillingJob(
                job_type="payment_reconciliation",
                provider="yookassa",
                object_type="payment_order",
                object_id=str(order_id),
                idempotency_key=f"reconcile:{order_id}",
                status="claimed",
                attempt_count=2,
                claimed_by="dead-worker",
                claim_id=uuid4(),
                claimed_at=datetime.now(UTC) - timedelta(minutes=5),
                lease_until=datetime.now(UTC) - timedelta(seconds=1),
                last_error_code="worker_lost",
            )
        )

    status = await PaymentStatusService(payment_db, 60).refresh(user_id)

    assert status is not None and status.reconciliation_requested
    async with payment_db() as session:
        job = await session.scalar(select(BillingJob).where(BillingJob.object_id == str(order_id)))
    assert job is not None
    assert job.status == "pending"
    assert job.claim_id is None
    assert job.claimed_by is None
    assert job.claimed_at is None
    assert job.lease_until is None
    assert job.attempt_count == 2
    assert job.last_error_code == "worker_lost"


async def test_user_refresh_surfaces_manual_review_reason_without_granting_access(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user_id, order_id = await create_order(
        payment_db,
        provider="yookassa",
        checkout_id="manual-review-yookassa",
    )
    async with payment_db.begin() as session:
        order = await session.get(PaymentOrder, order_id, with_for_update=True)
        assert order is not None
        order.status = "manual_review"
        order.failure_code = "amount_mismatch"

    status = await PaymentStatusService(payment_db, 60).refresh(user_id)

    assert status is not None
    assert status.status == "manual_review"
    assert status.failure_code == "amount_mismatch"
    assert not status.reconciliation_requested
    async with payment_db() as session:
        jobs = await session.scalar(select(func.count()).select_from(BillingJob))
    assert jobs == 0
