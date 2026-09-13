"""Regression coverage for privacy-safe reading feedback attribution."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.bot.reading_feedback_handlers import _feedback_stage_code
from app.domain.reading import ReadingStatus
from app.domain.reading_history import ReadingHistoryChoice
from app.providers.analytics import OracleProductEvent
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.reading_history import ReadingHistoryService


class RecordingAnalyticsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.calls.append((user_id, event, dict(properties or {})))


def _history(status: ReadingStatus) -> tuple[ReadingHistoryChoice, ...]:
    return (
        ReadingHistoryChoice(
            reading_id=uuid4(),
            persona_code="tarot",
            topic="relationships",
            status=status.value,
            created_at=datetime.now(UTC),
        ),
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ReadingStatus.PREVIEW_READY, "preview"),
        (ReadingStatus.FULL_READY, "full"),
    ],
)
async def test_feedback_stage_is_resolved_from_server_metadata(
    status: ReadingStatus,
    expected: str,
) -> None:
    service_mock = AsyncMock(spec=ReadingHistoryService)
    service_mock.ready_metadata.return_value = _history(status)
    service = cast("ReadingHistoryService", service_mock)

    stage = await _feedback_stage_code(service, uuid4(), uuid4())

    assert stage == expected


async def test_feedback_stage_falls_back_when_metadata_lookup_fails() -> None:
    service_mock = AsyncMock(spec=ReadingHistoryService)
    service_mock.ready_metadata.side_effect = RuntimeError("database unavailable")
    service = cast("ReadingHistoryService", service_mock)

    stage = await _feedback_stage_code(service, uuid4(), uuid4())

    assert stage == "unknown"


async def test_feedback_analytics_keeps_only_structured_attribution_context() -> None:
    client = RecordingAnalyticsClient()
    analytics = OracleProductAnalytics(client)
    user_id = uuid4()
    reading_id = uuid4()

    await analytics.track(
        user_id,
        OracleProductEvent.READING_FEEDBACK_SUBMITTED,
        {
            "reaction_code": "miss_too_general",
            "reading_id": reading_id,
            "stage_code": "preview",
        },
    )

    assert client.calls == [
        (
            str(user_id),
            OracleProductEvent.READING_FEEDBACK_SUBMITTED.value,
            {
                "event_version": "oracle-product-events-v1",
                "reaction_code": "miss_too_general",
                "reading_id": str(reading_id),
                "stage_code": "preview",
            },
        )
    ]


async def test_feedback_analytics_accepts_unknown_stage_fallback() -> None:
    client = RecordingAnalyticsClient()
    analytics = OracleProductAnalytics(client)

    await analytics.track(
        uuid4(),
        OracleProductEvent.READING_FEEDBACK_SUBMITTED,
        {
            "reaction_code": "hit",
            "reading_id": uuid4(),
            "stage_code": "unknown",
        },
    )

    assert client.calls[0][2]["stage_code"] == "unknown"


async def test_feedback_analytics_rejects_unexpected_content_fields() -> None:
    analytics = OracleProductAnalytics(RecordingAnalyticsClient())

    with pytest.raises(ValueError, match="safe contract"):
        await analytics.track(
            uuid4(),
            OracleProductEvent.READING_FEEDBACK_SUBMITTED,
            {
                "reaction_code": "hit",
                "reading_id": uuid4(),
                "stage_code": "full",
                "answer_text": "private reading content",
            },
        )
