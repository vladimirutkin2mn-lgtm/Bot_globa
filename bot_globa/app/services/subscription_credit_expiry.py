"""Retire the unused part of each finished subscription period.

A monthly plan lends credits for one month. Without this sweep a single month's
subscription would hand over a permanent balance, and one subscribe-then-cancel would
undercut every other way of paying. Purchased credits are untouched — only what a
subscription period granted can lapse, and only after that period has closed.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.subscription_models import SubscriptionPeriod
from app.services.credits_service import CreditsService, ExpiryOutcome

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpirySweepResult:
    examined: int = 0
    expired_periods: int = 0
    expired_credits: int = 0


async def expire_closed_periods(
    sessions: async_sessionmaker[AsyncSession],
    credits: CreditsService,
    *,
    batch_size: int = 100,
) -> ExpirySweepResult:
    """Settle one bounded batch of closed periods, oldest first."""

    async with sessions() as session:
        period_ids = list(
            await session.scalars(
                select(SubscriptionPeriod.id)
                .where(
                    SubscriptionPeriod.credits_expired_at.is_(None),
                    SubscriptionPeriod.status == "paid",
                    SubscriptionPeriod.period_end <= datetime.now(UTC),
                )
                .order_by(SubscriptionPeriod.period_end)
                .limit(batch_size)
            )
        )
    expired_periods = 0
    expired_credits = 0
    for period_id in period_ids:
        result = await credits.expire_subscription_period(period_id)
        if result.outcome is ExpiryOutcome.EXPIRED:
            expired_periods += 1
            expired_credits += result.expired
        elif result.outcome not in {
            ExpiryOutcome.NOTHING_TO_EXPIRE,
            ExpiryOutcome.ALREADY_EXPIRED,
        }:
            # Another worker or a late provider event moved the period; the next sweep
            # picks it up rather than forcing a decision on stale state.
            logger.info(
                "subscription_expiry_skipped period=%s outcome=%s", period_id, result.outcome
            )
    return ExpirySweepResult(len(period_ids), expired_periods, expired_credits)
