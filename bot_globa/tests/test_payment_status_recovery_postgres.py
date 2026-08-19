"""Production-shaped recovery checks for the user-facing payment refresh path."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BillingJob, PaymentOrder
from app.services.payment_status_service import PaymentStatusService
from tests.payment_postgres_helpers import create_order

pytestmark = pytest.mark.postgres


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
