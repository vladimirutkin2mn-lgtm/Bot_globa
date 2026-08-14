"""Real PostgreSQL transactional billing outbox delivery guarantees."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BillingOutboxEvent
from app.services.billing_outbox_service import BillingOutboxWorker

pytestmark = pytest.mark.postgres


class BlockingAnalytics:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def track(self, user_id, event, properties=None):  # type: ignore[no-untyped-def]
        self.started.set()
        await self.release.wait()


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls = 0

    async def track(self, user_id, event, properties=None):  # type: ignore[no-untyped-def]
        self.calls += 1


class FailingAnalytics:
    def __init__(self) -> None:
        self.calls = 0

    async def track(self, user_id, event, properties=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise RuntimeError("analytics unavailable")


class FailOnceAnalytics:
    def __init__(self) -> None:
        self.calls = 0

    async def track(self, user_id, event, properties=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient analytics failure")


async def create_outbox_event(payment_db: async_sessionmaker[AsyncSession]) -> UUID:
    async with payment_db.begin() as session:
        event = BillingOutboxEvent(
            aggregate_type="payment_order",
            aggregate_id=str(uuid4()),
            event_type="purchase_completed",
            payload={},
            idempotency_key=f"outbox:{uuid4()}",
        )
        session.add(event)
        await session.flush()
        return event.id


async def test_outbox_idempotency_key_is_unique_in_database(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    idempotency_key = f"outbox:{uuid4()}"
    async with payment_db.begin() as session:
        session.add(
            BillingOutboxEvent(
                aggregate_type="payment_order",
                aggregate_id=str(uuid4()),
                event_type="purchase_completed",
                payload={},
                idempotency_key=idempotency_key,
            )
        )

    async with payment_db() as session:
        session.add(
            BillingOutboxEvent(
                aggregate_type="payment_order",
                aggregate_id=str(uuid4()),
                event_type="purchase_completed",
                payload={},
                idempotency_key=idempotency_key,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_completed_outbox_event_is_not_delivered_again(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    event_id = await create_outbox_event(payment_db)
    analytics = RecordingAnalytics()
    worker = BillingOutboxWorker(payment_db, analytics)

    assert await worker.run_once("completion-worker")
    assert not await worker.run_once("completion-worker")

    async with payment_db() as session:
        persisted = await session.get(BillingOutboxEvent, event_id)
    assert analytics.calls == 1
    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.completed_at is not None


async def test_stale_outbox_delivery_cannot_overwrite_reclaimed_completion(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    event_id = await create_outbox_event(payment_db)
    blocked = BlockingAnalytics()
    task = asyncio.create_task(
        BillingOutboxWorker(payment_db, blocked, lease_seconds=1).run_once("a")
    )
    await blocked.started.wait()
    async with payment_db.begin() as session:
        claimed = await session.get(BillingOutboxEvent, event_id)
        assert claimed is not None
        claimed.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    recorder = RecordingAnalytics()
    assert await BillingOutboxWorker(payment_db, recorder).run_once("b")
    blocked.release.set()
    await task
    async with payment_db() as session:
        persisted = await session.get(BillingOutboxEvent, event_id)
    assert recorder.calls == 1
    assert persisted is not None and persisted.status == "completed"


async def test_transient_delivery_failure_retries_then_completes(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    event_id = await create_outbox_event(payment_db)
    analytics = FailOnceAnalytics()
    worker = BillingOutboxWorker(payment_db, analytics, retry_seconds=0, max_attempts=3)

    assert await worker.run_once("retry-worker")
    async with payment_db() as session:
        after_failure = await session.get(BillingOutboxEvent, event_id)
    assert after_failure is not None
    assert after_failure.status == "pending"
    assert after_failure.attempt_count == 1
    assert after_failure.last_error_code == "delivery_failed"

    assert await worker.run_once("retry-worker")
    async with payment_db() as session:
        completed = await session.get(BillingOutboxEvent, event_id)
    assert analytics.calls == 2
    assert completed is not None
    assert completed.status == "completed"
    assert completed.attempt_count == 2
    assert completed.completed_at is not None


async def test_exhausted_delivery_retries_require_manual_review(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    event_id = await create_outbox_event(payment_db)
    analytics = FailingAnalytics()
    worker = BillingOutboxWorker(payment_db, analytics, retry_seconds=0, max_attempts=2)

    assert await worker.run_once("failing-worker")
    assert await worker.run_once("failing-worker")
    assert not await worker.run_once("failing-worker")

    async with payment_db() as session:
        persisted = await session.get(BillingOutboxEvent, event_id)
    assert analytics.calls == 2
    assert persisted is not None
    assert persisted.status == "manual_review"
    assert persisted.attempt_count == 2
    assert persisted.last_error_code == "delivery_failed"
    assert persisted.claim_id is None
    assert persisted.claimed_by is None
    assert persisted.lease_until is None
