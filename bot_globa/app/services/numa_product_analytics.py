"""Typed facade for Numa product-funnel analytics."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.providers.analytics import AnalyticsClient
from app.providers.numa_product_analytics import (
    NUMA_PRODUCT_EVENT_VERSION,
    ProductFlow,
    ProductFunnelEvent,
    ProductSource,
    validate_numa_product_event,
)

type FunnelValue = str | int | bool | UUID | StrEnum


@dataclass(frozen=True, slots=True)
class ProductAttribution:
    """Stable, privacy-safe dimensions reused across the product funnel."""

    flow: ProductFlow
    source: ProductSource
    scenario_version: str
    experiment_assignment: str = "control"
    conversion_hook: str = "conversion_hook_v1"
    test_traffic: bool = False
    calculation_timezone: str = "Europe/Moscow"


class NumaProductAnalytics:
    """Build validated product events before handing them to the shared client."""

    def __init__(self, client: AnalyticsClient) -> None:
        self._client = client

    async def track(
        self,
        *,
        user_id: UUID | None,
        entity_id: UUID,
        event: ProductFunnelEvent,
        attribution: ProductAttribution,
        properties: Mapping[str, FunnelValue | None] | None = None,
    ) -> None:
        payload: dict[str, str] = {
            "event_version": NUMA_PRODUCT_EVENT_VERSION,
            "entity_id": str(entity_id),
            "flow": attribution.flow.value,
            "source": attribution.source.value,
            "scenario_version": attribution.scenario_version,
            "experiment_assignment": attribution.experiment_assignment,
            "conversion_hook": attribution.conversion_hook,
            "test_traffic": "true" if attribution.test_traffic else "false",
            "calculation_timezone": attribution.calculation_timezone,
        }
        for key, value in (properties or {}).items():
            if value is not None:
                payload[key] = self._value(value)
        safe = validate_numa_product_event(event.value, payload)
        await self._client.track(
            None if user_id is None else str(user_id),
            event.value,
            safe,
        )

    @staticmethod
    def _value(value: FunnelValue) -> str:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, StrEnum):
            return value.value
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
