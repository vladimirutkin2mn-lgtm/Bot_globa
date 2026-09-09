"""Durable unlock outcome tests without database, Telegram or LLM I/O."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.db.reading_models import Reading
from app.domain.reading import ReadingAccess, ReadingStatus
from app.domain.reading_result import ReadingResult
from app.services.credits_service import RefundOutcome, SpendOutcome
from app.services.monetized_reading import (
    MonetizedReadingService,
    MonetizedReadingStatus,
)
from app.services.numa_reading_funnel_signal import (
    ReadingFunnelOutcome,
    consume_reading_funnel_signal,
)


class FakeCredits:
    def __init__(
        self,
        outcome: SpendOutcome,
        *,
        transaction_id: UUID | None = None,
        balance: int = 0,
    ) -> None:
        self.outcome = outcome
        self.transaction_id = transaction_id
        self.balance = balance
        self.spend_calls = 0

    async def spend_reading(self, user_id: UUID, reading_id: UUID, price: int):
        self.spend_calls += 1
        return SimpleNamespace(
            outcome=self.outcome,
            transaction_id=self.transaction_id,
            balance=self.balance,
        )

    async def refund_reading_if_not_full(
        self,
        user_id: UUID,
        reading_id: UUID,
        transaction_id: UUID,
        price: int,
    ) -> RefundOutcome:
        return RefundOutcome.REFUNDED


class FakeReadings:
    def __init__(self) -> None:
        self.promotions = 0

    async def load_result(self, reading_id: UUID, user_id: UUID):
        return None

    async def promote_full_access(
        self,
        reading_id: UUID,
        user_id: UUID,
        cost_units: int,
        transaction_id: UUID,
    ) -> Reading:
        self.promotions += 1
        return cast(Reading, SimpleNamespace())


class StubMonetizedReadingService(MonetizedReadingService):
    def __init__(self, state: object, credits: FakeCredits, readings: FakeReadings) -> None:
        super().__init__(
            cast(Any, None),
            cast(Any, credits),
            readings,
            price_credits=3,
        )
        self.state = state

    async def _state(self, reading_id: UUID, user_id: UUID) -> Reading | None:
        return cast(Reading, self.state)

    async def _validated_result(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> ReadingResult | None:
        return cast(ReadingResult, object())


def preview_state() -> object:
    return SimpleNamespace(
        status=ReadingStatus.PREVIEW_READY.value,
        access_level=ReadingAccess.PREVIEW.value,
    )


@pytest.mark.asyncio
async def test_successful_promotion_marks_new_durable_unlock() -> None:
    user_id, reading_id, transaction_id = uuid4(), uuid4(), uuid4()
    credits = FakeCredits(SpendOutcome.SPENT, transaction_id=transaction_id)
    readings = FakeReadings()
    service = StubMonetizedReadingService(preview_state(), credits, readings)

    result = await service.unlock_full(reading_id, user_id)
    signal = consume_reading_funnel_signal()

    assert result.status is MonetizedReadingStatus.FULL_COMPLETED
    assert result.newly_unlocked is True
    assert readings.promotions == 1
    assert signal is not None
    assert signal.outcome is ReadingFunnelOutcome.FULL_UNLOCKED
    assert signal.reading_id == reading_id
    assert signal.user_id == user_id


@pytest.mark.asyncio
async def test_already_full_reading_is_not_counted_as_new_unlock() -> None:
    user_id, reading_id = uuid4(), uuid4()
    credits = FakeCredits(SpendOutcome.SPENT, transaction_id=uuid4())
    readings = FakeReadings()
    state = SimpleNamespace(
        status=ReadingStatus.FULL_READY.value,
        access_level=ReadingAccess.FULL.value,
    )
    service = StubMonetizedReadingService(state, credits, readings)

    result = await service.unlock_full(reading_id, user_id)
    signal = consume_reading_funnel_signal()

    assert result.status is MonetizedReadingStatus.FULL_COMPLETED
    assert result.newly_unlocked is False
    assert credits.spend_calls == 0
    assert readings.promotions == 0
    assert signal is None


@pytest.mark.asyncio
async def test_insufficient_balance_emits_paywall_candidate_only() -> None:
    user_id, reading_id = uuid4(), uuid4()
    credits = FakeCredits(SpendOutcome.INSUFFICIENT_BALANCE, balance=1)
    readings = FakeReadings()
    service = StubMonetizedReadingService(preview_state(), credits, readings)

    result = await service.unlock_full(reading_id, user_id)
    signal = consume_reading_funnel_signal()

    assert result.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS
    assert result.newly_unlocked is False
    assert result.balance == 1
    assert readings.promotions == 0
    assert signal is not None
    assert signal.outcome is ReadingFunnelOutcome.PAYWALL_REQUIRED
