"""Contract tests for the P1 Numa product funnel analytics."""

from collections.abc import Mapping
from uuid import uuid4

import pytest

from app.providers.numa_product_analytics import (
    NUMA_PRODUCT_EVENT_VERSION,
    ProductAnalyticsContractError,
    ProductFlow,
    ProductFunnelEvent,
    ProductSource,
    UnlockKind,
    numa_product_event_identity,
    validate_numa_product_event,
)
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution


class RecordingAnalyticsClient:
    def __init__(self) -> None:
        self.events: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.events.append((user_id, event, dict(properties or {})))


def _base_properties(entity_id: str) -> dict[str, str]:
    return {
        "event_version": NUMA_PRODUCT_EVENT_VERSION,
        "entity_id": entity_id,
        "flow": ProductFlow.PERSONAL.value,
        "source": ProductSource.NORMAL_START.value,
        "scenario_version": "personal_oracle_v1",
        "experiment_assignment": "control",
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": "false",
        "calculation_timezone": "Europe/Moscow",
    }


@pytest.mark.asyncio
async def test_complete_free_answer_has_required_attribution() -> None:
    client = RecordingAnalyticsClient()
    analytics = NumaProductAnalytics(client)
    user_id, reading_id = uuid4(), uuid4()

    await analytics.track(
        user_id=user_id,
        entity_id=reading_id,
        event=ProductFunnelEvent.FREE_ANSWER_DELIVERED,
        attribution=ProductAttribution(
            flow=ProductFlow.PERSONAL,
            source=ProductSource.NORMAL_START,
            scenario_version="personal_oracle_v1",
        ),
        properties={"delivery_status": "confirmed"},
    )

    assert len(client.events) == 1
    subject, event, properties = client.events[0]
    assert subject == str(user_id)
    assert event == ProductFunnelEvent.FREE_ANSWER_DELIVERED.value
    assert properties["flow"] == "personal"
    assert properties["source"] == "normal_start"
    assert properties["conversion_hook"] == "conversion_hook_v1"
    assert properties["delivery_status"] == "confirmed"


def test_group_source_is_distinct_from_personal_source() -> None:
    properties = _base_properties(str(uuid4()))
    properties["flow"] = ProductFlow.GROUP.value
    properties["source"] = ProductSource.GROUP_COMPATIBILITY.value

    safe = validate_numa_product_event(ProductFunnelEvent.ENTRY.value, properties)

    assert safe["flow"] == "group"
    assert safe["source"] == "group_compatibility"


def test_unlock_kind_separates_existing_credit_from_new_purchase() -> None:
    for unlock_kind in UnlockKind:
        properties = _base_properties(str(uuid4()))
        properties.update(
            {
                "unlock_kind": unlock_kind.value,
                "product_code": "reading_single",
            }
        )
        safe = validate_numa_product_event(ProductFunnelEvent.FULL_UNLOCKED.value, properties)
        assert safe["unlock_kind"] == unlock_kind.value


def test_sensitive_or_arbitrary_payload_is_rejected_without_echo() -> None:
    sentinel = "private-question-sentinel"
    properties = _base_properties(str(uuid4()))
    properties["question"] = sentinel

    with pytest.raises(ProductAnalyticsContractError) as raised:
        validate_numa_product_event(ProductFunnelEvent.ENTRY.value, properties)

    assert sentinel not in str(raised.value)


def test_same_business_entity_deduplicates_retried_delivery() -> None:
    user_id, entity_id = str(uuid4()), str(uuid4())
    properties = _base_properties(entity_id)
    properties["delivery_status"] = "confirmed"

    first = numa_product_event_identity(
        user_id,
        ProductFunnelEvent.FREE_ANSWER_DELIVERED.value,
        properties,
    )
    second = numa_product_event_identity(
        user_id,
        ProductFunnelEvent.FREE_ANSWER_DELIVERED.value,
        properties,
    )

    assert first == second
    assert first[1] == f"numa_free_answer_delivered:{entity_id}"


def test_test_campaign_is_explicitly_excludable() -> None:
    properties = _base_properties(str(uuid4()))
    properties["source"] = ProductSource.TEST_CAMPAIGN.value
    properties["test_traffic"] = "true"

    safe = validate_numa_product_event(ProductFunnelEvent.ENTRY.value, properties)

    assert safe["source"] == "test_campaign"
    assert safe["test_traffic"] == "true"
