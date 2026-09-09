"""Reading-funnel analytics tests without Telegram, database or LLM I/O."""

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest

from app.providers.numa_product_analytics import ProductFlow, ProductSource
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution
from app.services.numa_reading_funnel import (
    NumaReadingFunnelAnalytics,
    ReadingFunnelCandidate,
)
from app.services.numa_reading_funnel_signal import (
    ReadingFunnelOutcome,
    record_reading_funnel_signal,
)


class FakeReadingFunnelStore:
    def __init__(self, candidate: ReadingFunnelCandidate | None) -> None:
        self.value = candidate
        self.lookups: list[tuple[UUID, UUID]] = []

    async def candidate(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> ReadingFunnelCandidate | None:
        self.lookups.append((reading_id, user_id))
        return self.value


class CaptureAnalyticsClient:
    def __init__(self) -> None:
        self.events: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.events.append((user_id, event, dict(properties or {})))


def candidate() -> ReadingFunnelCandidate:
    user_id, reading_id = uuid4(), uuid4()
    return ReadingFunnelCandidate(
        user_id=user_id,
        reading_id=reading_id,
        attribution=ProductAttribution(
            flow=ProductFlow.PERSONAL,
            source=ProductSource.NORMAL_START,
            scenario_version="tarot_reader_v1",
        ),
    )


@pytest.mark.asyncio
async def test_paywall_is_confirmed_only_after_successful_handler() -> None:
    item = candidate()
    capture = CaptureAnalyticsClient()
    service = NumaReadingFunnelAnalytics(
        FakeReadingFunnelStore(item),
        NumaProductAnalytics(capture),
    )

    record_reading_funnel_signal(
        ReadingFunnelOutcome.PAYWALL_REQUIRED,
        item.reading_id,
        item.user_id,
    )
    confirmed = await service.confirm_current_outcome(handler_succeeded=False)
    assert confirmed is False
    assert capture.events == []

    record_reading_funnel_signal(
        ReadingFunnelOutcome.PAYWALL_REQUIRED,
        item.reading_id,
        item.user_id,
    )
    confirmed = await service.confirm_current_outcome(handler_succeeded=True)

    assert confirmed is True
    assert len(capture.events) == 1
    subject, event, payload = capture.events[0]
    assert subject == str(item.user_id)
    assert event == "numa_paywall_shown"
    assert payload["entity_id"] == str(item.reading_id)
    assert payload["flow"] == "personal"
    assert payload["source"] == "normal_start"


@pytest.mark.asyncio
async def test_durable_unlock_is_recorded_even_when_handler_later_fails() -> None:
    item = candidate()
    capture = CaptureAnalyticsClient()
    service = NumaReadingFunnelAnalytics(
        FakeReadingFunnelStore(item),
        NumaProductAnalytics(capture),
    )
    record_reading_funnel_signal(
        ReadingFunnelOutcome.FULL_UNLOCKED,
        item.reading_id,
        item.user_id,
    )

    confirmed = await service.confirm_current_outcome(handler_succeeded=False)

    assert confirmed is True
    assert len(capture.events) == 1
    subject, event, payload = capture.events[0]
    assert subject == str(item.user_id)
    assert event == "numa_full_unlocked"
    assert payload["unlock_kind"] == "existing_credit"
    assert payload["product_code"] == "reading_single"


@pytest.mark.asyncio
async def test_missing_safe_attribution_drops_funnel_event() -> None:
    user_id, reading_id = uuid4(), uuid4()
    capture = CaptureAnalyticsClient()
    service = NumaReadingFunnelAnalytics(
        FakeReadingFunnelStore(None),
        NumaProductAnalytics(capture),
    )
    record_reading_funnel_signal(
        ReadingFunnelOutcome.PAYWALL_REQUIRED,
        reading_id,
        user_id,
    )

    confirmed = await service.confirm_current_outcome(handler_succeeded=True)

    assert confirmed is False
    assert capture.events == []


def test_candidate_contains_no_sensitive_or_telegram_fields() -> None:
    item = candidate()

    assert not hasattr(item, "telegram_user_id")
    assert not hasattr(item, "question")
    assert not hasattr(item, "answer")
    assert not hasattr(item, "payment_token")
