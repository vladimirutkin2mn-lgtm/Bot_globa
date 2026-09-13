"""Typed, versioned facade for privacy-safe AI-oracle product events."""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from uuid import UUID

from app.providers.analytics import (
    PRODUCT_EVENT_TAXONOMY_VERSION,
    AnalyticsClient,
    OracleProductEvent,
    validate_event_properties,
)

type OracleAnalyticsValue = str | int | bool | UUID | StrEnum

_FEEDBACK_CONTEXT_KEYS = frozenset({"reading_id", "stage_code"})
_FEEDBACK_STAGES = frozenset({"preview", "full", "unknown"})


class OracleProductAnalytics:
    """Normalize code-like metadata and reject content before delivery."""

    def __init__(self, client: AnalyticsClient) -> None:
        self._client = client

    async def track(
        self,
        user_id: UUID | None,
        event: OracleProductEvent,
        properties: Mapping[str, OracleAnalyticsValue | None],
    ) -> None:
        if "event_version" in properties:
            raise ValueError("event_version is managed by the oracle analytics facade")
        normalized = {
            "event_version": PRODUCT_EVENT_TAXONOMY_VERSION,
            **{key: self._value(value) for key, value in properties.items() if value is not None},
        }
        feedback_context: dict[str, str] = {}
        contract_properties = normalized
        if event is OracleProductEvent.READING_FEEDBACK_SUBMITTED:
            feedback_context = self._feedback_context(normalized)
            contract_properties = {
                key: value for key, value in normalized.items() if key not in _FEEDBACK_CONTEXT_KEYS
            }
        safe = {
            **validate_event_properties(event.value, contract_properties),
            **feedback_context,
        }
        await self._client.track(
            None if user_id is None else str(user_id),
            event.value,
            safe,
        )

    @staticmethod
    def category_codes(values: Iterable[str | StrEnum]) -> str:
        """Encode a deterministic set of risk codes without free-form text."""

        normalized = sorted(
            {value.value if isinstance(value, StrEnum) else value for value in values if value}
        )
        return "+".join(normalized) if normalized else "none"

    @staticmethod
    def _feedback_context(properties: Mapping[str, str]) -> dict[str, str]:
        """Validate the only extra feedback dimensions allowed outside raw content."""

        reading_id = properties.get("reading_id")
        stage_code = properties.get("stage_code")
        if reading_id is None or stage_code not in _FEEDBACK_STAGES:
            raise ValueError("reading feedback attribution is invalid")
        try:
            normalized_reading_id = str(UUID(reading_id))
        except ValueError:
            raise ValueError("reading feedback attribution is invalid") from None
        return {
            "reading_id": normalized_reading_id,
            "stage_code": stage_code,
        }

    @staticmethod
    def _value(value: OracleAnalyticsValue) -> str:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, StrEnum):
            return value.value
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
