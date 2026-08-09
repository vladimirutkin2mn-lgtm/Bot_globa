"""Historical Analysis access compatibility for the retired relationship product.

The relationship-analysis product is retired, but existing ledger rows can still
reference Analysis records.  Keep the smallest possible mutation boundary for
validating a historical spend and monotonically promoting that record to full
access.  New product code must use Reading-domain monetization instead.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Analysis, CreditTransaction


class LegacyAnalysisAccessOutcome(StrEnum):
    UPDATED = "updated"
    ALREADY_FULL_SAME_TRANSACTION = "already_full_same_transaction"
    NOT_FOUND = "not_found"
    DELETED = "deleted"
    NOT_COMPLETED = "not_completed"
    TRANSACTION_MISMATCH = "transaction_mismatch"
    ACCESS_CONFLICT = "access_conflict"


class LegacyAnalysisAccessService:
    """Validate immutable ledger linkage before promoting historical access."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def grant_full_access(
        self,
        analysis_id: UUID,
        user_id: UUID,
        cost: int,
        transaction_id: UUID,
    ) -> LegacyAnalysisAccessOutcome:
        async with self._sessions.begin() as session:
            analysis = await session.scalar(
                select(Analysis)
                .where(Analysis.id == analysis_id, Analysis.user_id == user_id)
                .with_for_update()
            )
            if analysis is None:
                return LegacyAnalysisAccessOutcome.NOT_FOUND
            if analysis.status == "deleted":
                return LegacyAnalysisAccessOutcome.DELETED
            if analysis.status != "completed":
                return LegacyAnalysisAccessOutcome.NOT_COMPLETED

            spend = await session.scalar(
                select(CreditTransaction)
                .where(CreditTransaction.id == transaction_id)
                .with_for_update()
            )
            if (
                spend is None
                or spend.user_id != user_id
                or spend.analysis_id != analysis_id
                or spend.type != "spend"
                or spend.amount != -cost
            ):
                return LegacyAnalysisAccessOutcome.TRANSACTION_MISMATCH
            refund = await session.scalar(
                select(CreditTransaction.id)
                .where(CreditTransaction.reverses_transaction_id == spend.id)
                .with_for_update()
            )
            if refund is not None:
                return LegacyAnalysisAccessOutcome.TRANSACTION_MISMATCH

            if analysis.report_access == "full":
                return (
                    LegacyAnalysisAccessOutcome.ALREADY_FULL_SAME_TRANSACTION
                    if analysis.full_access_transaction_id == transaction_id
                    and analysis.cost_units == cost
                    else LegacyAnalysisAccessOutcome.TRANSACTION_MISMATCH
                )
            if analysis.report_access not in {"none", "preview"}:
                return LegacyAnalysisAccessOutcome.ACCESS_CONFLICT

            analysis.report_access = "full"
            analysis.cost_units = cost
            analysis.full_access_transaction_id = transaction_id
            await session.flush()
            if (
                analysis.report_access != "full"
                or analysis.cost_units != cost
                or analysis.full_access_transaction_id != transaction_id
            ):
                return LegacyAnalysisAccessOutcome.ACCESS_CONFLICT
        return LegacyAnalysisAccessOutcome.UPDATED
