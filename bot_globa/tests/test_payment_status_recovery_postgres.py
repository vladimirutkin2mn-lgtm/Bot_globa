"""Production-shaped recovery checks for the user-facing payment refresh path."""

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
    second = await service.refresh(user_id)

    assert first is not None
    assert first.order_id == order_id
    assert first.status == "pending"
    assert first.reconciliation_requested
    assert second is not None and not second.reconciliation_requested
    async with payment_db() as session:
        jobs = await session.scalar(select(func.count()).select_from(BillingJob))
        job = await session.scalar(select(BillingJob))
    assert jobs == 1
    assert job is not None
    assert job.job_type == "payment_reconciliation"
    assert job.object_id == str(order_id)


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
