"""Transactional, append-only credit ledger operations."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Analysis, CreditReservation, CreditTransaction, Subscription, User
from app.db.reading_models import Reading
from app.db.subscription_models import SubscriptionPeriod


class SpendOutcome(StrEnum):
    SPENT = "spent"
    ALREADY_SPENT_ACTIVE = "already_spent_active"
    ALREADY_SPENT = "already_spent_active"
    ALREADY_SPENT_REFUNDED = "already_spent_refunded"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    ANALYSIS_NOT_FOUND = "analysis_not_found"
    READING_NOT_FOUND = "reading_not_found"
    INVALID_AMOUNT = "invalid_amount"


class RefundOutcome(StrEnum):
    REFUNDED = "refunded"
    ALREADY_REFUNDED = "already_refunded"
    SPEND_NOT_FOUND = "spend_not_found"
    INVALID_SPEND = "invalid_spend"
    AUTHORIZATION_MISMATCH = "authorization_mismatch"
    ACCESS_ALREADY_GRANTED = "access_already_granted"


class GrantOutcome(StrEnum):
    GRANTED = "granted"
    ALREADY_GRANTED = "already_granted"
    USER_NOT_FOUND = "user_not_found"
    INVALID_AMOUNT = "invalid_amount"


class ExpiryOutcome(StrEnum):
    EXPIRED = "expired"
    NOTHING_TO_EXPIRE = "nothing_to_expire"
    ALREADY_EXPIRED = "already_expired"
    PERIOD_NOT_FOUND = "period_not_found"
    PERIOD_NOT_PAID = "period_not_paid"
    PERIOD_STILL_OPEN = "period_still_open"


@dataclass(frozen=True)
class SpendResult:
    outcome: SpendOutcome
    transaction_id: UUID | None = None
    balance: int = 0


@dataclass(frozen=True)
class ExpiryResult:
    outcome: ExpiryOutcome
    expired: int = 0
    balance: int = 0


class CreditsService:
    """Serialize each user's debits by locking their durable user row."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def balance(self, user_id: UUID) -> int:
        async with self._sessions() as session:
            return int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                        CreditTransaction.user_id == user_id
                    )
                )
                or 0
            )

    async def spend(self, user_id: UUID, analysis_id: UUID, amount: int) -> SpendResult:
        if amount < 1:
            return SpendResult(SpendOutcome.INVALID_AMOUNT)
        key = f"analysis_full_access:{analysis_id}"
        async with self._sessions.begin() as session:
            if (
                await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
                is None
            ):
                return SpendResult(SpendOutcome.ANALYSIS_NOT_FOUND)
            analysis = await session.scalar(
                select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id)
            )
            if analysis is None:
                return SpendResult(SpendOutcome.ANALYSIS_NOT_FOUND)
            existing = await session.scalar(
                select(CreditTransaction).where(CreditTransaction.idempotency_key == key)
            )
            balance = int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                        CreditTransaction.user_id == user_id
                    )
                )
                or 0
            )
            if existing is not None:
                if not (
                    existing.user_id == user_id
                    and existing.analysis_id == analysis_id
                    and existing.type == "spend"
                    and existing.amount == -amount
                ):
                    return SpendResult(SpendOutcome.ANALYSIS_NOT_FOUND, balance=balance)
                refunded = await session.scalar(
                    select(CreditTransaction.id).where(
                        CreditTransaction.reverses_transaction_id == existing.id
                    )
                )
                if refunded is not None:
                    return SpendResult(SpendOutcome.ALREADY_SPENT_REFUNDED, balance=balance)
                return SpendResult(SpendOutcome.ALREADY_SPENT_ACTIVE, existing.id, balance)
            reserved = int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditReservation.credit_units), 0)).where(
                        CreditReservation.user_id == user_id,
                        CreditReservation.status == "active",
                    )
                )
                or 0
            )
            available = max(0, balance - reserved)
            if available < amount:
                return SpendResult(SpendOutcome.INSUFFICIENT_BALANCE, balance=available)
            row = CreditTransaction(
                user_id=user_id,
                type="spend",
                amount=-amount,
                idempotency_key=key,
                analysis_id=analysis_id,
            )
            session.add(row)
            await session.flush()
            return SpendResult(SpendOutcome.SPENT, row.id, available - amount)

    async def spend_reading(
        self,
        user_id: UUID,
        reading_id: UUID,
        amount: int,
    ) -> SpendResult:
        if amount < 1:
            return SpendResult(SpendOutcome.INVALID_AMOUNT)
        key = f"reading_full_access:{reading_id}"
        async with self._sessions.begin() as session:
            user = await session.scalar(
                select(User)
                .where(User.id == user_id, User.privacy_status == "active")
                .with_for_update()
            )
            if user is None:
                return SpendResult(SpendOutcome.READING_NOT_FOUND)
            reading = await session.scalar(
                select(Reading).where(
                    Reading.id == reading_id,
                    Reading.user_id == user_id,
                    Reading.status.in_(("preview_ready", "full_ready")),
                )
            )
            if reading is None:
                return SpendResult(SpendOutcome.READING_NOT_FOUND)
            existing = await session.scalar(
                select(CreditTransaction).where(CreditTransaction.idempotency_key == key)
            )
            balance = int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                        CreditTransaction.user_id == user_id
                    )
                )
                or 0
            )
            if existing is not None:
                if not (
                    existing.user_id == user_id
                    and existing.reading_id == reading_id
                    and existing.analysis_id is None
                    and existing.type == "spend"
                    and existing.amount == -amount
                ):
                    return SpendResult(SpendOutcome.READING_NOT_FOUND, balance=balance)
                refunded = await session.scalar(
                    select(CreditTransaction.id).where(
                        CreditTransaction.reverses_transaction_id == existing.id
                    )
                )
                if refunded is not None:
                    return SpendResult(SpendOutcome.ALREADY_SPENT_REFUNDED, balance=balance)
                return SpendResult(SpendOutcome.ALREADY_SPENT_ACTIVE, existing.id, balance)
            reserved = int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditReservation.credit_units), 0)).where(
                        CreditReservation.user_id == user_id,
                        CreditReservation.status == "active",
                    )
                )
                or 0
            )
            available = max(0, balance - reserved)
            if available < amount:
                return SpendResult(SpendOutcome.INSUFFICIENT_BALANCE, balance=available)
            row = CreditTransaction(
                user_id=user_id,
                type="spend",
                amount=-amount,
                idempotency_key=key,
                reading_id=reading_id,
            )
            session.add(row)
            await session.flush()
            return SpendResult(SpendOutcome.SPENT, row.id, available - amount)

    async def refund_reading_if_not_full(
        self,
        user_id: UUID,
        reading_id: UUID,
        spend_id: UUID,
        expected_cost: int,
    ) -> RefundOutcome:
        async with self._sessions.begin() as session:
            reading = await session.scalar(
                select(Reading)
                .where(Reading.id == reading_id, Reading.user_id == user_id)
                .with_for_update()
            )
            if reading is None:
                return RefundOutcome.AUTHORIZATION_MISMATCH
            spend = await session.scalar(
                select(CreditTransaction).where(CreditTransaction.id == spend_id).with_for_update()
            )
            if spend is None:
                return RefundOutcome.SPEND_NOT_FOUND
            if spend.user_id != user_id or spend.reading_id != reading_id:
                return RefundOutcome.AUTHORIZATION_MISMATCH
            if (
                spend.analysis_id is not None
                or spend.type != "spend"
                or spend.amount != -expected_cost
            ):
                return RefundOutcome.INVALID_SPEND
            if (
                reading.full_access_transaction_id == spend_id
                and reading.cost_units == expected_cost
            ):
                return RefundOutcome.ACCESS_ALREADY_GRANTED
            existing = await session.scalar(
                select(CreditTransaction.id).where(
                    CreditTransaction.reverses_transaction_id == spend.id
                )
            )
            if existing is not None:
                return RefundOutcome.ALREADY_REFUNDED
            session.add(
                CreditTransaction(
                    user_id=user_id,
                    type="refund",
                    amount=-spend.amount,
                    idempotency_key=f"refund:{spend.id}",
                    reading_id=reading_id,
                    reverses_transaction_id=spend.id,
                )
            )
            return RefundOutcome.REFUNDED

    async def refund(self, user_id: UUID, analysis_id: UUID, spend_id: UUID) -> RefundOutcome:
        """Compatibility wrapper that delegates to the safe analysis-aware boundary."""
        async with self._sessions() as session:
            spend = await session.get(CreditTransaction, spend_id)
            if spend is None:
                return RefundOutcome.SPEND_NOT_FOUND
            if spend.user_id != user_id or spend.analysis_id != analysis_id:
                return RefundOutcome.AUTHORIZATION_MISMATCH
            if spend.type != "spend" or spend.amount >= 0:
                return RefundOutcome.INVALID_SPEND
            expected_cost = -spend.amount
        return await self.refund_if_not_full(user_id, analysis_id, spend_id, expected_cost)

    async def refund_if_not_full(
        self, user_id: UUID, analysis_id: UUID, spend_id: UUID, expected_cost: int
    ) -> RefundOutcome:
        """Refund under the same lock order used to grant full access."""
        async with self._sessions.begin() as session:
            analysis = await session.scalar(
                select(Analysis)
                .where(Analysis.id == analysis_id, Analysis.user_id == user_id)
                .with_for_update()
            )
            if analysis is None:
                return RefundOutcome.AUTHORIZATION_MISMATCH
            spend = await session.scalar(
                select(CreditTransaction).where(CreditTransaction.id == spend_id).with_for_update()
            )
            if spend is None:
                return RefundOutcome.SPEND_NOT_FOUND
            if spend.user_id != user_id or spend.analysis_id != analysis_id:
                return RefundOutcome.AUTHORIZATION_MISMATCH
            if spend.type != "spend" or spend.amount != -expected_cost:
                return RefundOutcome.INVALID_SPEND
            if (
                analysis.status == "completed"
                and analysis.report_access == "full"
                and analysis.full_access_transaction_id == spend_id
                and analysis.cost_units == expected_cost
            ):
                return RefundOutcome.ACCESS_ALREADY_GRANTED
            existing = await session.scalar(
                select(CreditTransaction.id).where(
                    CreditTransaction.reverses_transaction_id == spend.id
                )
            )
            if existing is not None:
                return RefundOutcome.ALREADY_REFUNDED
            session.add(
                CreditTransaction(
                    user_id=user_id,
                    type="refund",
                    amount=-spend.amount,
                    idempotency_key=f"refund:{spend.id}",
                    analysis_id=analysis_id,
                    reverses_transaction_id=spend.id,
                )
            )
            return RefundOutcome.REFUNDED

    async def expire_subscription_period(self, period_id: UUID) -> ExpiryResult:
        """Retire whatever a finished subscription period granted and nobody spent.

        Purchased credits keep their old meaning and never expire. Spends are therefore
        charged against subscription credits first: what a user still holds beyond their
        permanent balance is exactly what this period lent them, so that difference —
        capped by the period's own grant — is what lapses.
        """

        async with self._sessions.begin() as session:
            period = await session.scalar(
                select(SubscriptionPeriod)
                .where(SubscriptionPeriod.id == period_id)
                .with_for_update()
            )
            if period is None:
                return ExpiryResult(ExpiryOutcome.PERIOD_NOT_FOUND)
            if period.credits_expired_at is not None:
                return ExpiryResult(ExpiryOutcome.ALREADY_EXPIRED)
            if period.status != "paid" or period.purchase_transaction_id is None:
                return ExpiryResult(ExpiryOutcome.PERIOD_NOT_PAID)
            if period.period_end > datetime.now(UTC):
                return ExpiryResult(ExpiryOutcome.PERIOD_STILL_OPEN)
            user_id = await session.scalar(
                select(Subscription.user_id).where(Subscription.id == period.subscription_id)
            )
            if user_id is None:
                return ExpiryResult(ExpiryOutcome.PERIOD_NOT_FOUND)
            # Take the same lock a spend does, so a concurrent purchase or unlock cannot
            # settle between reading the balance and writing the compensating row.
            if (
                await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
                is None
            ):
                return ExpiryResult(ExpiryOutcome.PERIOD_NOT_FOUND)
            balance = await self._sum(session, CreditTransaction.user_id == user_id)
            lent_by_subscriptions = (
                select(SubscriptionPeriod.purchase_transaction_id)
                .join(Subscription, Subscription.id == SubscriptionPeriod.subscription_id)
                .where(Subscription.user_id == user_id)
            )
            # What the user owns outright: every credit they were given other than by a
            # subscription, less any purchase that was refunded. Debits are deliberately
            # excluded, which is what charges spending to the borrowed credits first.
            owned = await self._sum(
                session,
                CreditTransaction.user_id == user_id,
                CreditTransaction.amount > 0,
                CreditTransaction.id.not_in(lent_by_subscriptions),
            ) + await self._sum(
                session,
                CreditTransaction.user_id == user_id,
                CreditTransaction.type == "purchase_refund",
            )
            lapsing = min(max(0, balance - max(0, owned)), period.credits, max(0, balance))
            period.credits_expired_at = datetime.now(UTC)
            if lapsing == 0:
                return ExpiryResult(ExpiryOutcome.NOTHING_TO_EXPIRE, balance=balance)
            session.add(
                CreditTransaction(
                    user_id=user_id,
                    type="expiry",
                    amount=-lapsing,
                    idempotency_key=f"subscription:expiry:{period.id}",
                )
            )
            return ExpiryResult(ExpiryOutcome.EXPIRED, expired=lapsing, balance=balance - lapsing)

    @staticmethod
    async def _sum(session: AsyncSession, *conditions: ColumnElement[bool]) -> int:
        return int(
            await session.scalar(
                select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(*conditions)
            )
            or 0
        )

    async def grant(self, user_id: UUID, amount: int, key: str) -> GrantOutcome:
        if amount < 1:
            return GrantOutcome.INVALID_AMOUNT
        async with self._sessions.begin() as session:
            if (
                await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
                is None
            ):
                return GrantOutcome.USER_NOT_FOUND
            if (
                await session.scalar(
                    select(CreditTransaction.id).where(CreditTransaction.idempotency_key == key)
                )
                is not None
            ):
                return GrantOutcome.ALREADY_GRANTED
            session.add(
                CreditTransaction(user_id=user_id, type="grant", amount=amount, idempotency_key=key)
            )
            return GrantOutcome.GRANTED

    async def adjustment(self, user_id: UUID, amount: int, key: str) -> GrantOutcome:
        if amount == 0:
            return GrantOutcome.INVALID_AMOUNT
        async with self._sessions.begin() as session:
            if (
                await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
                is None
            ):
                return GrantOutcome.USER_NOT_FOUND
            if (
                await session.scalar(
                    select(CreditTransaction.id).where(CreditTransaction.idempotency_key == key)
                )
                is not None
            ):
                return GrantOutcome.ALREADY_GRANTED
            balance = int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                        CreditTransaction.user_id == user_id
                    )
                )
                or 0
            )
            if balance + amount < 0:
                return GrantOutcome.INVALID_AMOUNT
            session.add(
                CreditTransaction(
                    user_id=user_id, type="adjustment", amount=amount, idempotency_key=key
                )
            )
            return GrantOutcome.GRANTED
