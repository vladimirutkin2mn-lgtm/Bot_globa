"""Unit contracts for the versioned privacy-safe oracle event taxonomy."""

from collections.abc import Mapping
from enum import StrEnum
from uuid import uuid4

import pytest

from app.providers.analytics import (
    PRODUCT_EVENT_TAXONOMY_VERSION,
    AnalyticsContractError,
    OracleProductEvent,
    event_taxonomy_version,
    known_event_names,
    validate_event_properties,
)
from app.services.oracle_product_analytics import OracleProductAnalytics


class SampleCode(StrEnum):
    TAROT = "tarot_reader"
    DECISION = "decision"


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.calls.append((user_id, event, dict(properties or {})))


async def test_facade_normalizes_only_versioned_structured_metadata() -> None:
    recording = RecordingAnalytics()
    analytics = OracleProductAnalytics(recording)
    user_id, reading_id = uuid4(), uuid4()

    await analytics.track(
        user_id,
        OracleProductEvent.READING_PREVIEW_READY,
        {
            "reading_id": reading_id,
            "persona_code": SampleCode.TAROT,
            "topic_code": SampleCode.DECISION,
            "attempt_count": 1,
            "repair_used": False,
            "memory_count": 2,
        },
    )

    assert recording.calls == [
        (
            str(user_id),
            "reading_preview_ready",
            {
                "event_version": PRODUCT_EVENT_TAXONOMY_VERSION,
                "reading_id": str(reading_id),
                "persona_code": "tarot_reader",
                "topic_code": "decision",
                "attempt_count": "1",
                "repair_used": "false",
                "memory_count": "2",
            },
        )
    ]


async def test_facade_rejects_content_and_caller_managed_version() -> None:
    analytics = OracleProductAnalytics(RecordingAnalytics())

    with pytest.raises(AnalyticsContractError):
        await analytics.track(
            uuid4(),
            OracleProductEvent.READING_STARTED,
            {
                "reading_id": uuid4(),
                "persona_code": "tarot_reader",
                "topic_code": "decision",
                "question": "private-user-question",
            },
        )

    with pytest.raises(ValueError, match="managed by the oracle analytics facade"):
        await analytics.track(
            uuid4(),
            OracleProductEvent.PERSONA_SELECTED,
            {
                "event_version": "attacker-version",
                "persona_code": "tarot_reader",
                "topic_code": "decision",
            },
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"event_version": PRODUCT_EVENT_TAXONOMY_VERSION},
        {
            "event_version": "oracle-product-events-v2",
            "persona_code": "tarot_reader",
            "topic_code": "decision",
        },
        {
            "event_version": PRODUCT_EVENT_TAXONOMY_VERSION,
            "persona_code": "free form persona text",
            "topic_code": "decision",
        },
    ],
)
def test_direct_contract_requires_exact_version_and_required_codes(
    payload: dict[str, str],
) -> None:
    with pytest.raises(AnalyticsContractError):
        validate_event_properties("persona_selected", payload)


def test_taxonomy_is_complete_stable_and_category_sets_are_deterministic() -> None:
    names = set(known_event_names())

    assert {event.value for event in OracleProductEvent} <= names
    assert all(
        event_taxonomy_version(event.value) == PRODUCT_EVENT_TAXONOMY_VERSION
        for event in OracleProductEvent
    )
    assert OracleProductAnalytics.category_codes(
        ["financial", "medical", "financial"]
    ) == "financial+medical"
    assert OracleProductAnalytics.category_codes([]) == "none"
