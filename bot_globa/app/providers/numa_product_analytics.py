"""Typed P1 product-funnel analytics extension for Numa.

This module extends the existing analytics boundary without allowing arbitrary
properties. It intentionally stores only internal UUIDs and short code values.
Telegram identifiers, questions, answers, birth data and payment secrets are not
part of the contract.
"""

import re
from collections.abc import Mapping
from enum import StrEnum
from uuid import UUID

NUMA_PRODUCT_EVENT_VERSION = "numa-product-funnel-v1"

_SAFE_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}\Z")


class ProductFlow(StrEnum):
    PERSONAL = "personal"
    DAILY = "daily"
    GROUP = "group"


class ProductSource(StrEnum):
    NORMAL_START = "normal_start"
    DAILY_HOROSCOPE = "daily_horoscope"
    GROUP_CARD = "group_card"
    GROUP_COMPATIBILITY = "group_compatibility"
    GROUP_DUEL = "group_duel"
    GROUP_PARTY = "group_party"
    GROUP_EVENT = "group_event"
    GROUP_CHAT = "group_chat"
    SHARED_INSIGHT = "shared_insight"
    TEST_CAMPAIGN = "test_campaign"


class UnlockKind(StrEnum):
    EXISTING_CREDIT = "existing_credit"
    NEW_PURCHASE = "new_purchase"


class ProductFunnelEvent(StrEnum):
    ENTRY = "numa_entry"
    QUESTION_ACCEPTED = "numa_question_accepted"
    FREE_ANSWER_READY = "numa_free_answer_ready"
    FREE_ANSWER_DELIVERED = "numa_free_answer_delivered"
    PAYWALL_SHOWN = "numa_paywall_shown"
    CHECKOUT_STARTED = "numa_checkout_started"
    PURCHASE_CONFIRMED = "numa_purchase_confirmed"
    FULL_UNLOCKED = "numa_full_unlocked"
    REPEAT_ACTIVITY = "numa_repeat_activity"
    DAILY_PREPARED = "numa_daily_prepared"
    DAILY_DELIVERED = "numa_daily_delivered"
    DAILY_ACTION = "numa_daily_action"
    SHARE_CARD_SHOWN = "numa_share_card_shown"
    SHARE_INTENT = "numa_share_intent"
    RECIPIENT_ENTRY = "numa_recipient_entry"


class GroupFunnelEvent(StrEnum):
    """Anonymous P1-08 group funnel; attribution is intentionally code-only."""

    ENTRY_OPENED = "group_entry_opened"
    ADD_STARTED = "group_add_started"
    GAME_STARTED = "group_game_started"
    GAME_COMPLETED = "group_game_completed"
    TO_PRIVATE_CLICKED = "group_to_private_clicked"


GROUP_FUNNEL_SOURCE = "group_add"
GROUP_GAME_CODES = frozenset({"compatibility", "duel"})

_COMMON = frozenset(
    {
        "event_version",
        "entity_id",
        "flow",
        "source",
        "scenario_version",
        "experiment_assignment",
        "conversion_hook",
        "test_traffic",
        "calculation_timezone",
    }
)
_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    ProductFunnelEvent.ENTRY.value: _COMMON,
    ProductFunnelEvent.QUESTION_ACCEPTED.value: _COMMON,
    ProductFunnelEvent.FREE_ANSWER_READY.value: _COMMON | {"latency_ms"},
    ProductFunnelEvent.FREE_ANSWER_DELIVERED.value: _COMMON | {"delivery_status"},
    ProductFunnelEvent.PAYWALL_SHOWN.value: _COMMON,
    ProductFunnelEvent.CHECKOUT_STARTED.value: _COMMON | {"product_code", "provider"},
    ProductFunnelEvent.PURCHASE_CONFIRMED.value: _COMMON
    | {"product_code", "provider", "purchase_kind", "amount_minor", "currency"},
    ProductFunnelEvent.FULL_UNLOCKED.value: _COMMON | {"unlock_kind", "product_code"},
    ProductFunnelEvent.REPEAT_ACTIVITY.value: _COMMON | {"activity_kind", "day_bucket"},
    ProductFunnelEvent.DAILY_PREPARED.value: _COMMON | {"local_date"},
    ProductFunnelEvent.DAILY_DELIVERED.value: _COMMON | {"local_date", "delivery_status"},
    ProductFunnelEvent.DAILY_ACTION.value: _COMMON | {"local_date", "action_code"},
    ProductFunnelEvent.SHARE_CARD_SHOWN.value: _COMMON | {"share_format"},
    ProductFunnelEvent.SHARE_INTENT.value: _COMMON | {"share_format"},
    ProductFunnelEvent.RECIPIENT_ENTRY.value: _COMMON | {"campaign_code"},
}
_GROUP_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    GroupFunnelEvent.ENTRY_OPENED.value: frozenset({"source"}),
    GroupFunnelEvent.ADD_STARTED.value: frozenset({"source"}),
    GroupFunnelEvent.GAME_STARTED.value: frozenset({"source", "game"}),
    GroupFunnelEvent.GAME_COMPLETED.value: frozenset({"source", "game"}),
    GroupFunnelEvent.TO_PRIVATE_CLICKED.value: frozenset({"source", "game"}),
}

_REQUIRED_COMMON = frozenset(
    {
        "event_version",
        "entity_id",
        "flow",
        "source",
        "scenario_version",
        "experiment_assignment",
        "conversion_hook",
        "test_traffic",
        "calculation_timezone",
    }
)
_REQUIRED: dict[str, frozenset[str]] = dict.fromkeys(_EVENT_PROPERTIES, _REQUIRED_COMMON)
_REQUIRED.update(
    {
        ProductFunnelEvent.FREE_ANSWER_DELIVERED.value: _REQUIRED_COMMON | {"delivery_status"},
        ProductFunnelEvent.CHECKOUT_STARTED.value: _REQUIRED_COMMON | {"product_code", "provider"},
        ProductFunnelEvent.PURCHASE_CONFIRMED.value: _REQUIRED_COMMON
        | {"product_code", "provider", "purchase_kind", "amount_minor", "currency"},
        ProductFunnelEvent.FULL_UNLOCKED.value: _REQUIRED_COMMON | {"unlock_kind", "product_code"},
        ProductFunnelEvent.REPEAT_ACTIVITY.value: _REQUIRED_COMMON
        | {"activity_kind", "day_bucket"},
        ProductFunnelEvent.DAILY_PREPARED.value: _REQUIRED_COMMON | {"local_date"},
        ProductFunnelEvent.DAILY_DELIVERED.value: _REQUIRED_COMMON
        | {"local_date", "delivery_status"},
        ProductFunnelEvent.DAILY_ACTION.value: _REQUIRED_COMMON | {"local_date", "action_code"},
        ProductFunnelEvent.SHARE_CARD_SHOWN.value: _REQUIRED_COMMON | {"share_format"},
        ProductFunnelEvent.SHARE_INTENT.value: _REQUIRED_COMMON | {"share_format"},
        ProductFunnelEvent.RECIPIENT_ENTRY.value: _REQUIRED_COMMON | {"campaign_code"},
    }
)
_INTEGER_KEYS = frozenset({"amount_minor", "latency_ms"})


class ProductAnalyticsContractError(ValueError):
    """Generic error that never echoes rejected values."""

    def __init__(self) -> None:
        super().__init__("Numa product analytics event violates the safe contract")


def is_numa_product_event(event: str) -> bool:
    return event in _EVENT_PROPERTIES


def is_numa_group_event(event: str) -> bool:
    return event in _GROUP_EVENT_PROPERTIES


def validate_numa_group_event(
    event: str,
    properties: Mapping[str, str] | None,
) -> dict[str, str]:
    """Accept only aggregate source/game codes for P1-08 group telemetry."""

    allowed = _GROUP_EVENT_PROPERTIES.get(event)
    if allowed is None:
        raise ProductAnalyticsContractError
    supplied = dict(properties or {})
    if supplied.keys() != allowed:
        raise ProductAnalyticsContractError
    if supplied.get("source") != GROUP_FUNNEL_SOURCE:
        raise ProductAnalyticsContractError
    game = supplied.get("game")
    if game is not None and game not in GROUP_GAME_CODES:
        raise ProductAnalyticsContractError
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value.isprintable()
        or _SAFE_CODE.fullmatch(value) is None
        for value in supplied.values()
    ):
        raise ProductAnalyticsContractError
    return supplied


def validate_numa_product_event(event: str, properties: Mapping[str, str] | None) -> dict[str, str]:
    """Validate one product event using an explicit allow-list."""

    allowed = _EVENT_PROPERTIES.get(event)
    if allowed is None:
        raise ProductAnalyticsContractError
    supplied = dict(properties or {})
    required = _REQUIRED[event]
    if not required <= supplied.keys() or not supplied.keys() <= allowed:
        raise ProductAnalyticsContractError
    if supplied.get("event_version") != NUMA_PRODUCT_EVENT_VERSION:
        raise ProductAnalyticsContractError
    if supplied.get("flow") not in {value.value for value in ProductFlow}:
        raise ProductAnalyticsContractError
    if supplied.get("source") not in {value.value for value in ProductSource}:
        raise ProductAnalyticsContractError
    if supplied.get("test_traffic") not in {"true", "false"}:
        raise ProductAnalyticsContractError
    if "unlock_kind" in supplied and supplied["unlock_kind"] not in {
        value.value for value in UnlockKind
    }:
        raise ProductAnalyticsContractError

    for key, value in supplied.items():
        if not isinstance(value, str) or not value or len(value) > 128 or not value.isprintable():
            raise ProductAnalyticsContractError
        if key == "entity_id":
            try:
                UUID(value)
            except ValueError:
                raise ProductAnalyticsContractError from None
        elif key in _INTEGER_KEYS:
            try:
                int(value)
            except ValueError:
                raise ProductAnalyticsContractError from None
        elif _SAFE_CODE.fullmatch(value) is None:
            raise ProductAnalyticsContractError
    return supplied


def numa_product_event_identity(
    user_id: str | None, event: str, properties: Mapping[str, str]
) -> tuple[str | None, str]:
    """Use an internal business UUID to deduplicate retried Telegram updates."""

    safe = validate_numa_product_event(event, properties)
    subject = _validated_optional_uuid(user_id)
    entity_id = safe["entity_id"]
    return subject, f"{event}:{entity_id}"


def _validated_optional_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        raise ProductAnalyticsContractError from None
