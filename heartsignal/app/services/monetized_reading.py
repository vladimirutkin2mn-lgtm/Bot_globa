"""Financial orchestration for unlocking an already generated oracle reading."""

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_models import Reading
from app.domain.reading import ReadingAccess, ReadingStatus
from app.domain.reading_result import ReadingResult
from app.services.credits_service import CreditsService, RefundOutcome, SpendOutcome


class PaidReadingStore(Protocol):
    async def load_result(self, reading_id: UUID, user_id: UUID) -> dict[str, object] | None: ...

    async def promote_full_access(
        self,
        reading_id: UUID,
        user_id: UUID,
        cost_units: int,
        transaction_id: UUID,
    ) -> Reading: ...


class MonetizedReadingStatus(StrEnum):
    FULL_COMPLETED = "full_completed"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    NOT_FOUND = "not_found"
    DELETED = "deleted"
    NOT_READY = "not_ready"
    CORRUPTED_RESULT = "corrupted_result"
    TECHNICAL_FAILURE_REFUNDED = "technical_failure_refunded"
    TECHNICAL_FAILURE_ALREADY_REFUNDED = "technical_failure_already_refunded"
    TECHNICAL_FAILURE_REFUND_FAILED = "technical_failure_refund_failed"


@dataclass(frozen=True, slots=True)
class MonetizedReadingResult:
    status: MonetizedReadingStatus
    result: ReadingResult | None = None
    balance: int | None = None


class MonetizedReadingService:
    """Charge once, grant once and refund unless durable full access was granted."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        credits: CreditsService,
        readings: PaidReadingStore,
        price_credits: int,
    ) -> None:
        if price_credits < 1:
            raise ValueError("reading price must be positive")
        self._sessions = sessions
        self._credits = credits
        self._readings = readings
        self._price = price_credits

    @property
    def price_credits(self) -> int:
        return self._price

    async def unlock_full(self, reading_id: UUID, user_id: UUID) -> MonetizedReadingResult:
        state = await self._state(reading_id, user_id)
        if state is None:
            return MonetizedReadingResult(MonetizedReadingStatus.NOT_FOUND)
        if state.status == ReadingStatus.DELETED.value:
            return MonetizedReadingResult(MonetizedReadingStatus.DELETED)
        if state.status not in {
            ReadingStatus.PREVIEW_READY.value,
            ReadingStatus.FULL_READY.value,
        }:
            return MonetizedReadingResult(MonetizedReadingStatus.NOT_READY)

        result = await self._validated_result(reading_id, user_id)
        if result is None:
            return MonetizedReadingResult(MonetizedReadingStatus.CORRUPTED_RESULT)
        if state.access_level == ReadingAccess.FULL.value:
            return MonetizedReadingResult(MonetizedReadingStatus.FULL_COMPLETED, result)

        spent = await self._credits.spend_reading(user_id, reading_id, self._price)
        if spent.outcome is SpendOutcome.INSUFFICIENT_BALANCE:
            return MonetizedReadingResult(
                MonetizedReadingStatus.INSUFFICIENT_CREDITS,
                balance=spent.balance,
            )
        if spent.transaction_id is None or spent.outcome not in {
            SpendOutcome.SPENT,
            SpendOutcome.ALREADY_SPENT_ACTIVE,
        }:
            return MonetizedReadingResult(MonetizedReadingStatus.NOT_FOUND)

        try:
            await self._readings.promote_full_access(
                reading_id,
                user_id,
                self._price,
                spent.transaction_id,
            )
        except asyncio.CancelledError:
            try:
                await self._credits.refund_reading_if_not_full(
                    user_id,
                    reading_id,
                    spent.transaction_id,
                    self._price,
                )
            finally:
                raise
        except Exception:
            return await self._refund_result(
                user_id,
                reading_id,
                spent.transaction_id,
            )
        return MonetizedReadingResult(MonetizedReadingStatus.FULL_COMPLETED, result)

    async def _state(self, reading_id: UUID, user_id: UUID) -> Reading | None:
        async with self._sessions() as session:
            value = await session.scalar(
                select(Reading).where(Reading.id == reading_id, Reading.user_id == user_id)
            )
            return value

    async def _validated_result(self, reading_id: UUID, user_id: UUID) -> ReadingResult | None:
        try:
            payload = await self._readings.load_result(reading_id, user_id)
            return None if payload is None else ReadingResult.model_validate(payload)
        except (ValidationError, ValueError, TypeError):
            return None

    async def _refund_result(
        self,
        user_id: UUID,
        reading_id: UUID,
        spend_id: UUID,
    ) -> MonetizedReadingResult:
        refund = await self._credits.refund_reading_if_not_full(
            user_id,
            reading_id,
            spend_id,
            self._price,
        )
        if refund is RefundOutcome.ACCESS_ALREADY_GRANTED:
            result = await self._validated_result(reading_id, user_id)
            return MonetizedReadingResult(MonetizedReadingStatus.FULL_COMPLETED, result)
        if refund is RefundOutcome.REFUNDED:
            status = MonetizedReadingStatus.TECHNICAL_FAILURE_REFUNDED
        elif refund is RefundOutcome.ALREADY_REFUNDED:
            status = MonetizedReadingStatus.TECHNICAL_FAILURE_ALREADY_REFUNDED
        else:
            status = MonetizedReadingStatus.TECHNICAL_FAILURE_REFUND_FAILED
        return MonetizedReadingResult(status)
