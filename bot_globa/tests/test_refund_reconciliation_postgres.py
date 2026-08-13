"""Real-PostgreSQL exactly-once refund reconciliation regressions."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from aiogram.types import StarTransactions
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    BillingJob,
    CreditReservation,
    CreditTransaction,
    PaymentOrder,
    RefundRequest,
    User,
)
from app.providers.payments.refund_gateway import (
    AuthoritativeRefund,
    CreateRefund,
    RefundCapabilities,
)
from app.providers.payments.telegram_stars import TelegramStarsGateway
from app.services.billing_job_worker import BillingJobWorker
from app.services.payment_completion_service import PaymentCompletionService
from app.services.refund_reconciliation_service import RefundReconciliationService
from app.services.refund_service import RefundRequestOutcome, RefundService

pytestmark = pytest.mark.postgres


class FakeRefundGateway:
    refund_capabilities = RefundCapabilities(partial_refunds=True)

    def __init__(self, status: str = "succeeded") -> None:
        self.status = status
        self.create_calls = 0
        self.fetch_calls = 0
        self.refund_id = "refund-provider-1"
        self.payment_id = "payment-provider-1"
        self.amount_minor = 1_000
        self.currency = "EUR"

    def fact(self) -> AuthoritativeRefund:
        return AuthoritativeRefund(
            provider="stripe",
            provider_refund_id=self.refund_id,
            provider_payment_id=self.payment_id,
            status=self.status,
            amount_minor=self.amount_minor,
            currency=self.currency,
            provider_status=self.status,
            failure_code="declined" if self.status == "failed" else None,
            live_mode=False,
        )

    async def create_refund(self, request: CreateRefund) -> AuthoritativeRefund:
        self.create_calls += 1
        assert request.provider_payment_id == self.payment_id
        assert request.amount_minor == 1_000
        return self.fact()

    async def fetch_refund(self, refund_id: str) -> AuthoritativeRefund:
        self.fetch_calls += 1
        assert refund_id == self.refund_id
        return self.fact()


@pytest.fixture
async def refund_db() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://u:p@db/x",
        telegram_bot_token=SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        content_encryption_key=SecretStr("refund-reconciliation-test-key"),
        payment_provider="stripe",
        billing_enabled=True,
        refunds_enabled=True,
        stripe_enabled=True,
    )


async def requested_refund(
    sessions: async_sessionmaker[AsyncSession], gateway: FakeRefundGateway
) -> tuple[UUID, UUID, UUID]:
    async with sessions.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Refund")
        session.add(user)
        await session.flush()
        order = PaymentOrder(
            user_id=user.id,
            provider="stripe",
            product_code="reading_pack_5",
            status="completed",
            credits=5,
            amount_minor=1_000,
            currency="EUR",
            provider_payment_id=gateway.payment_id,
            provider_status="succeeded",
            provider_live_mode=False,
            completed_at=datetime.now(UTC),
            commercial_snapshot={},
        )
        session.add(order)
        await session.flush()
        session.add(
            CreditTransaction(
                user_id=user.id,
                type="purchase",
                amount=5,
                idempotency_key=f"purchase:{order.id}",
                payment_order_id=order.id,
                product_code=order.product_code,
                external_payment_id=order.provider_payment_id,
                external_payment_provider="stripe",
            )
        )
        user_id, order_id = user.id, order.id
    result = await RefundService(
        sessions,
        settings(),
        {"stripe": gateway},
    ).request_refund(user_id, order_id, 5)
    assert result.outcome is RefundRequestOutcome.CREATED
    assert result.refund is not None
    return user_id, order_id, result.refund.id


def worker(
    sessions: async_sessionmaker[AsyncSession], gateway: FakeRefundGateway
) -> BillingJobWorker:
    return BillingJobWorker(
        sessions,
        {},
        PaymentCompletionService(sessions),
        lease_seconds=60,
        retry_base_seconds=1,
        max_attempts=3,
        refund_gateways={"stripe": gateway},
        refund_processor=RefundReconciliationService(sessions, pending_retry_seconds=1),
    )


async def ledger_refund_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.type == "purchase_refund")
            )
            or 0
        )


async def test_success_consumes_reservation_and_posts_one_negative_ledger_entry(
    refund_db: async_sessionmaker[AsyncSession],
) -> None:
    gateway = FakeRefundGateway("succeeded")
    _, order_id, refund_id = await requested_refund(refund_db, gateway)
    jobs = worker(refund_db, gateway)

    assert await jobs.run_once("worker-1")
    assert not await jobs.run_once("worker-1")

    async with refund_db() as session:
        refund = await session.get(RefundRequest, refund_id)
        reservation = await session.scalar(
            select(CreditReservation).where(CreditReservation.refund_request_id == refund_id)
        )
        ledger = await session.scalar(
            select(CreditTransaction).where(CreditTransaction.refund_request_id == refund_id)
        )
        purchase = await session.scalar(
            select(CreditTransaction).where(
                CreditTransaction.payment_order_id == order_id,
                CreditTransaction.type == "purchase",
            )
        )
        assert refund is not None and refund.status == "succeeded"
        assert refund.provider_refund_id == gateway.refund_id
        assert reservation is not None and reservation.status == "consumed"
        assert ledger is not None and ledger.amount == -5
        assert purchase is not None and ledger.original_purchase_transaction_id == purchase.id
    assert await ledger_refund_count(refund_db) == 1
    assert gateway.create_calls == 1


async def test_authoritative_failure_releases_credits_without_ledger_entry(
    refund_db: async_sessionmaker[AsyncSession],
) -> None:
    gateway = FakeRefundGateway("failed")
    user_id, _, refund_id = await requested_refund(refund_db, gateway)

    assert await worker(refund_db, gateway).run_once("worker-1")

    async with refund_db() as session:
        refund = await session.get(RefundRequest, refund_id)
        reservation = await session.scalar(
            select(CreditReservation).where(CreditReservation.refund_request_id == refund_id)
        )
        balance = int(
            await session.scalar(
                select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                    CreditTransaction.user_id == user_id
                )
            )
            or 0
        )
        assert refund is not None and refund.status == "failed"
        assert refund.failure_code == "declined"
        assert reservation is not None and reservation.status == "released"
        assert balance == 5
    assert await ledger_refund_count(refund_db) == 0


async def test_pending_refund_reuses_provider_identity_then_completes(
    refund_db: async_sessionmaker[AsyncSession],
) -> None:
    gateway = FakeRefundGateway("pending")
    _, _, refund_id = await requested_refund(refund_db, gateway)
    jobs = worker(refund_db, gateway)

    assert await jobs.run_once("worker-1")
    async with refund_db.begin() as session:
        refund = await session.get(RefundRequest, refund_id)
        job = await session.scalar(select(BillingJob).where(BillingJob.object_id == str(refund_id)))
        assert refund is not None and refund.status == "provider_pending"
        assert refund.provider_refund_id == gateway.refund_id
        assert job is not None and job.status == "pending"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    gateway.status = "succeeded"

    assert await jobs.run_once("worker-2")

    async with refund_db() as session:
        refund = await session.get(RefundRequest, refund_id)
        assert refund is not None and refund.status == "succeeded"
    assert gateway.create_calls == 1
    assert gateway.fetch_calls == 1
    assert await ledger_refund_count(refund_db) == 1


async def test_provider_amount_mismatch_keeps_reservation_for_manual_review(
    refund_db: async_sessionmaker[AsyncSession],
) -> None:
    gateway = FakeRefundGateway("succeeded")
    _, _, refund_id = await requested_refund(refund_db, gateway)
    gateway.amount_minor = 999

    assert await worker(refund_db, gateway).run_once("worker-1")

    async with refund_db() as session:
        refund = await session.get(RefundRequest, refund_id)
        reservation = await session.scalar(
            select(CreditReservation).where(CreditReservation.refund_request_id == refund_id)
        )
        job = await session.scalar(select(BillingJob).where(BillingJob.object_id == str(refund_id)))
        assert refund is not None and refund.status == "manual_review"
        assert refund.failure_code == "refund_amount_mismatch"
        assert reservation is not None and reservation.status == "active"
        assert job is not None and job.status == "manual_review"
    assert await ledger_refund_count(refund_db) == 0


class FakeStarsBot:
    """Records the Bot API arguments a Stars refund must be able to produce."""

    def __init__(self) -> None:
        self.refunded: list[tuple[int, str]] = []

    async def refund_star_payment(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        request_timeout: int | None = None,
    ) -> bool:
        self.refunded.append((user_id, telegram_payment_charge_id))
        return True

    async def get_star_transactions(
        self,
        offset: int | None = None,
        limit: int | None = None,
        request_timeout: int | None = None,
    ) -> StarTransactions:
        return StarTransactions(transactions=[])

    async def edit_user_star_subscription(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        is_canceled: bool,
        request_timeout: int | None = None,
    ) -> bool:
        return True


async def test_stars_refund_reaches_the_bot_api_with_the_buyer_telegram_id(
    refund_db: async_sessionmaker[AsyncSession],
) -> None:
    """`refundStarPayment` needs the buyer's Telegram id, which lives only on the user row."""
    telegram_user_id = 990_001
    charge_id = "stars-charge-refundable"
    async with refund_db.begin() as session:
        user = User(telegram_user_id=telegram_user_id, first_name="Stars")
        session.add(user)
        await session.flush()
        order = PaymentOrder(
            user_id=user.id,
            provider="telegram_stars",
            product_code="reading_pack_5",
            status="completed",
            credits=5,
            amount_minor=300,
            currency="XTR",
            market="TELEGRAM",
            provider_payment_id=charge_id,
            provider_status="paid",
            provider_live_mode=True,
            completed_at=datetime.now(UTC),
            commercial_snapshot={},
        )
        session.add(order)
        await session.flush()
        session.add(
            CreditTransaction(
                user_id=user.id,
                type="purchase",
                amount=5,
                idempotency_key=f"purchase:{order.id}",
                payment_order_id=order.id,
                product_code=order.product_code,
                external_payment_id=charge_id,
                external_payment_provider="telegram_stars",
            )
        )
        user_id, order_id = user.id, order.id

    bot = FakeStarsBot()
    stars = TelegramStarsGateway(bot, timeout_seconds=5, reconciliation_pages=1)
    stars_settings = settings().model_copy(
        update={
            "payment_provider": "production",
            "telegram_stars_enabled": True,
            "telegram_stars_amount_reading_single": 75,
            "telegram_stars_amount_reading_pack_5": 300,
        }
    )
    requested = await RefundService(
        refund_db, stars_settings, {"telegram_stars": stars}
    ).request_refund(user_id, order_id, 5)
    assert requested.outcome is RefundRequestOutcome.CREATED
    assert requested.refund is not None
    jobs = BillingJobWorker(
        refund_db,
        {},
        PaymentCompletionService(refund_db),
        lease_seconds=60,
        retry_base_seconds=1,
        max_attempts=3,
        refund_gateways={"telegram_stars": stars},
        refund_processor=RefundReconciliationService(refund_db, pending_retry_seconds=1),
    )

    assert await jobs.run_once("worker-1")

    assert bot.refunded == [(telegram_user_id, charge_id)]
    async with refund_db() as session:
        refund = await session.get(RefundRequest, requested.refund.id)
        ledger = await session.scalar(
            select(CreditTransaction).where(
                CreditTransaction.refund_request_id == requested.refund.id
            )
        )
        assert refund is not None and refund.status == "succeeded"
        assert refund.provider_refund_id == f"stars-refund:{charge_id}"
        assert ledger is not None and ledger.amount == -5
    assert await ledger_refund_count(refund_db) == 1


async def test_partial_stars_refund_is_refused_before_any_provider_call(
    refund_db: async_sessionmaker[AsyncSession],
) -> None:
    """The Bot API can only reverse a whole charge, so a partial request must never start."""
    async with refund_db.begin() as session:
        user = User(telegram_user_id=990_002, first_name="Stars")
        session.add(user)
        await session.flush()
        order = PaymentOrder(
            user_id=user.id,
            provider="telegram_stars",
            product_code="reading_pack_5",
            status="completed",
            credits=5,
            amount_minor=300,
            currency="XTR",
            market="TELEGRAM",
            provider_payment_id="stars-charge-partial",
            provider_status="paid",
            provider_live_mode=True,
            completed_at=datetime.now(UTC),
            commercial_snapshot={},
        )
        session.add(order)
        await session.flush()
        session.add(
            CreditTransaction(
                user_id=user.id,
                type="purchase",
                amount=5,
                idempotency_key=f"purchase:{order.id}",
                payment_order_id=order.id,
                product_code=order.product_code,
                external_payment_id=order.provider_payment_id,
                external_payment_provider="telegram_stars",
            )
        )
        user_id, order_id = user.id, order.id

    bot = FakeStarsBot()
    stars = TelegramStarsGateway(bot, timeout_seconds=5, reconciliation_pages=1)
    stars_settings = settings().model_copy(
        update={
            "payment_provider": "production",
            "telegram_stars_enabled": True,
            "telegram_stars_amount_reading_single": 75,
            "telegram_stars_amount_reading_pack_5": 300,
        }
    )

    result = await RefundService(
        refund_db, stars_settings, {"telegram_stars": stars}
    ).request_refund(user_id, order_id, 2)

    assert result.outcome is RefundRequestOutcome.PARTIAL_UNSUPPORTED
    assert bot.refunded == []
