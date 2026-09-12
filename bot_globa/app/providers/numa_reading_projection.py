"""Project existing safe Reading lifecycle events into the P1 Numa funnel.

The projection receives only already allow-listed analytics metadata. It never sees the
question, answer, birth data or Telegram identity.
"""

from collections.abc import Mapping
from contextlib import suppress
from uuid import UUID

from app.domain.conversion_experiment import free_preview_experiment_assignment
from app.providers.analytics import OracleProductEvent
from app.providers.numa_product_analytics import (
    NUMA_PRODUCT_EVENT_VERSION,
    ProductFlow,
    ProductFunnelEvent,
    ProductSource,
    validate_numa_product_event,
)

_PERSONAL_PERSONAS = frozenset(
    {
        "tarot_reader",
        "love_oracle",
        "mystical_psychologist",
        "astrologer",
    }
)
_ATTRIBUTION_KEYS = (
    "flow",
    "source",
    "scenario_version",
    "experiment_assignment",
    "conversion_hook",
    "test_traffic",
    "calculation_timezone",
)


def project_personal_reading_event(
    event: str,
    properties: Mapping[str, str],
    latest_personal_entry: Mapping[str, str] | None = None,
    *,
    subject_id: str | None = None,
) -> tuple[str, dict[str, str]] | None:
    """Return one typed funnel event for a personal Reading transition, if applicable."""

    target = {
        OracleProductEvent.READING_STARTED.value: ProductFunnelEvent.QUESTION_ACCEPTED.value,
        OracleProductEvent.READING_PREVIEW_READY.value: ProductFunnelEvent.FREE_ANSWER_READY.value,
    }.get(event)
    if target is None:
        return None

    persona_code = properties.get("persona_code")
    reading_id = properties.get("reading_id")
    if persona_code not in _PERSONAL_PERSONAS or reading_id is None:
        return None

    experiment_assignment = "control"
    if subject_id is not None:
        with suppress(ValueError):
            experiment_assignment = free_preview_experiment_assignment(UUID(subject_id))

    projected = {
        "event_version": NUMA_PRODUCT_EVENT_VERSION,
        "entity_id": reading_id,
        "flow": ProductFlow.PERSONAL.value,
        "source": ProductSource.NORMAL_START.value,
        "scenario_version": f"{persona_code}_v1",
        "experiment_assignment": experiment_assignment,
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": "false",
        "calculation_timezone": "UTC",
    }
    if latest_personal_entry is not None and latest_personal_entry.get("flow") == "personal":
        for key in _ATTRIBUTION_KEYS:
            value = latest_personal_entry.get(key)
            if not value:
                continue
            if (
                key == "experiment_assignment"
                and value == "control"
                and experiment_assignment != "control"
            ):
                continue
            projected[key] = value

    return target, validate_numa_product_event(target, projected)
