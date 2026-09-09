"""Confirmed-delivery analytics tests without Telegram, database or LLM I/O."""

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest

from app.observability.context import reset_correlation_id, set_correlation_id
from app.providers.numa_product_analytics import ProductFlow, ProductSource
from app.services.numa_delivery_analytics import (
    FreeAnswerDeliveryCandidate,
    NumaDeliveryAnalytics,
)
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution


class FakeDeliveryStore:
    def __init__(self, candidate: FreeAnswerDeliveryCandidate | None) -> None:
        self.candidate = candidate
        self.correlation_ids: list[str] = []

    async def free_answer_candidate(
        self, correlation_id: str
    ) -> FreeAnswerDeliveryCandidate | None:
        self.correlation_ids.append(correlation_id)
        return self.candidate


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


@pytest.mark.asyncio
async def test_confirmed_delivery_uses_current_update_and_safe_attribution() -> None:
    user_id, reading_id = uuid4(), uuid4()
    store = FakeDeliveryStore(
        FreeAnswerDeliveryCandidate(
            user_id=user_id,
            reading_id=reading_id,
            attribution=ProductAttribution(
                flow=ProductFlow.PERSONAL,
                source=ProductSource.DAILY_HOROSCOPE,
                scenario_version="personal_day_forecast_v1",
                experiment_assignment="variant_b",
                calculation_timezone="Europe/Moscow",
            ),
        )
    )
    capture = CaptureAnalyticsClient()
    service = NumaDeliveryAnalytics(store, NumaProductAnalytics(capture))
    _, token = set_correlation_id("tg-update-777")
    try:
        confirmed = await service.confirm_current_free_answer()
    finally:
        reset_correlation_id(token)

    assert confirmed is True
    assert store.correlation_ids == ["tg-update-777"]
    assert len(capture.events) == 1
    subject, event, payload = capture.events[0]
    assert subject == str(user_id)
    assert event == "numa_free_answer_delivered"
    assert payload["entity_id"] == str(reading_id)
    assert payload["source"] == "daily_horoscope"
    assert payload["experiment_assignment"] == "variant_b"
    assert payload["delivery_status"] == "telegram_accepted"


@pytest.mark.asyncio
async def test_no_ready_preview_means_no_delivery_event() -> None:
    store = FakeDeliveryStore(None)
    capture = CaptureAnalyticsClient()
    service = NumaDeliveryAnalytics(store, NumaProductAnalytics(capture))
    _, token = set_correlation_id("tg-update-778")
    try:
        confirmed = await service.confirm_current_free_answer()
    finally:
        reset_correlation_id(token)

    assert confirmed is False
    assert capture.events == []


def test_candidate_contains_only_internal_ids_and_typed_attribution() -> None:
    candidate = FreeAnswerDeliveryCandidate(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        reading_id=UUID("22222222-2222-2222-2222-222222222222"),
        attribution=ProductAttribution(
            flow=ProductFlow.PERSONAL,
            source=ProductSource.NORMAL_START,
            scenario_version="tarot_reader_v1",
        ),
    )

    assert not hasattr(candidate, "telegram_user_id")
    assert not hasattr(candidate, "question")
    assert not hasattr(candidate, "answer")
