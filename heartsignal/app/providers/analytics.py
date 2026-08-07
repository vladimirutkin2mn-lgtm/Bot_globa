"""Privacy-preserving product analytics boundary and event contract."""

import logging
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol
from uuid import UUID

logger = logging.getLogger(__name__)

PRODUCT_EVENT_TAXONOMY_VERSION = "oracle-product-events-v1"
LEGACY_EVENT_TAXONOMY_VERSION = "legacy-platform-events-v1"

_SAFE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}\Z")
_UUID_KEYS = frozenset(
    {
        "analysis_id",
        "memory_item_id",
        "order_id",
        "reading_id",
        "refund_id",
        "subscription_id",
        "transaction_id",
        "user_id",
    }
)
_INTEGER_KEYS = frozenset(
    {
        "amount_minor",
        "attempt_count",
        "character_count_bucket",
        "chunk_count_bucket",
        "created_count",
        "credits",
        "deleted_count",
        "memory_count",
        "message_count_bucket",
        "model_inferred_count",
        "product_version",
        "score",
        "selected_count",
        "skipped_count",
        "user_stated_count",
    }
)


class EventScope(StrEnum):
    """Durable identity used to suppress duplicate transition events."""

    USER = "user"
    ANALYSIS = "analysis"
    READING = "reading"
    ORDER = "order"
    MEMORY_ITEM = "memory_item"
    ACCOUNT = "account"
    ACTION = "action"


class OracleProductEvent(StrEnum):
    """Stable v1 names for the AI-oracle product funnel."""

    PERSONA_SELECTED = "persona_selected"
    READING_STARTED = "reading_started"
    READING_PREVIEW_READY = "reading_preview_ready"
    READING_FULL_UNLOCKED = "reading_full_unlocked"
    READING_REOPENED = "reading_reopened"
    READING_FAILED = "reading_failed"
    BIRTH_PROFILE_CONSENT_GRANTED = "birth_profile_consent_granted"
    BIRTH_PROFILE_CONSENT_REVOKED = "birth_profile_consent_revoked"
    BIRTH_PROFILE_SAVED = "birth_profile_saved"
    BIRTH_PROFILE_DELETED = "birth_profile_deleted"
    ASTROLOGY_CALCULATION_COMPLETED = "astrology_calculation_completed"
    ASTROLOGY_CALCULATION_FAILED = "astrology_calculation_failed"
    MEMORY_CONSENT_GRANTED = "memory_consent_granted"
    MEMORY_CONSENT_REVOKED = "memory_consent_revoked"
    MEMORY_ITEM_CREATED = "memory_item_created"
    MEMORY_ITEM_DELETED = "memory_item_deleted"
    MEMORY_ITEM_CORRECTED = "memory_item_corrected"
    MEMORY_CLEARED = "memory_cleared"
    MEMORY_CONTEXT_USED = "memory_context_used"
    MEMORY_EXTRACTION_COMPLETED = "memory_extraction_completed"
    MEMORY_EXTRACTION_SKIPPED = "memory_extraction_skipped"
    MEMORY_EXTRACTION_FAILED = "memory_extraction_failed"
    READING_FOLLOWUP_REQUESTED = "reading_followup_requested"
    READING_FOLLOWUP_COMPLETED = "reading_followup_completed"
    READING_FOLLOWUP_FAILED = "reading_followup_failed"
    SHARE_PREVIEWED = "share_previewed"
    SHARE_CONFIRMED = "share_confirmed"
    SAFETY_INPUT_CLASSIFIED = "safety_input_classified"
    SAFETY_OUTPUT_REJECTED = "safety_output_rejected"


def _oracle_properties(*values: str) -> frozenset[str]:
    return frozenset(("event_version", *values))


_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    "bot_started": frozenset(),
    "main_menu_opened": frozenset(),
    "age_confirmed": frozenset(),
    "consent_accepted": frozenset({"consent_version"}),
    "onboarding_completed": frozenset({"consent_version"}),
    "analysis_started": frozenset({"analysis_id", "source_type"}),
    "conversation_submitted": frozenset(
        {
            "analysis_id",
            "source_type",
            "source_format",
            "message_count_bucket",
            "character_count_bucket",
        }
    ),
    "conversation_parsed": frozenset(
        {
            "analysis_id",
            "source_type",
            "source_format",
            "message_count_bucket",
            "character_count_bucket",
        }
    ),
    "conversation_rejected": frozenset({"analysis_id", "rejection_reason"}),
    "analysis_context_completed": frozenset({"analysis_id", "relationship_stage_code"}),
    "analysis_cancelled": frozenset({"analysis_id"}),
    "preview_viewed": frozenset({"analysis_id"}),
    "paywall_viewed": frozenset({"analysis_id"}),
    "credit_spent": frozenset({"analysis_id", "transaction_id", "credits"}),
    "credit_refunded": frozenset({"analysis_id", "transaction_id", "credits"}),
    "checkout_started": frozenset(
        {
            "order_id",
            "product_code",
            "product_version",
            "provider",
            "market",
            "currency",
            "credits",
            "mode",
        }
    ),
    "purchase_completed": frozenset(
        {
            "order_id",
            "product_code",
            "product_version",
            "provider",
            "market",
            "currency",
            "credits",
            "mode",
        }
    ),
    "payment_failed": frozenset(
        {
            "order_id",
            "product_code",
            "product_version",
            "provider",
            "market",
            "currency",
            "failure_code",
            "mode",
        }
    ),
    "analysis_processing_started": frozenset(
        {"analysis_id", "provider", "model", "prompt_version"}
    ),
    "analysis_completed": frozenset(
        {
            "analysis_id",
            "provider",
            "model",
            "prompt_version",
            "attempt_count",
            "repair_used",
            "latency_bucket",
            "input_token_bucket",
            "output_token_bucket",
        }
    ),
    "analysis_failed": frozenset(
        {
            "analysis_id",
            "provider",
            "model",
            "prompt_version",
            "attempt_count",
            "repair_used",
            "latency_bucket",
            "input_token_bucket",
            "output_token_bucket",
            "failure_code",
        }
    ),
    "analysis_feedback_submitted": frozenset({"analysis_id", "score"}),
    "analysis_history_opened": frozenset({"analysis_id"}),
    "analysis_report_delivered": frozenset(
        {"analysis_id", "source", "chunk_count_bucket"}
    ),
    "reply_suggestions_requested": frozenset({"analysis_id"}),
    "followup_requested": frozenset({"analysis_id"}),
    "analysis_deleted": frozenset({"analysis_id"}),
    "all_data_deleted": frozenset({"user_id"}),
    OracleProductEvent.PERSONA_SELECTED.value: _oracle_properties(
        "persona_code", "topic_code"
    ),
    OracleProductEvent.READING_STARTED.value: _oracle_properties(
        "reading_id",
        "persona_code",
        "topic_code",
        "engine_version",
        "prompt_version",
        "schema_version",
    ),
    OracleProductEvent.READING_PREVIEW_READY.value: _oracle_properties(
        "reading_id",
        "persona_code",
        "topic_code",
        "engine_version",
        "prompt_version",
        "schema_version",
        "attempt_count",
        "repair_used",
        "memory_count",
    ),
    OracleProductEvent.READING_FULL_UNLOCKED.value: _oracle_properties(
        "reading_id",
        "persona_code",
        "product_code",
        "product_version",
        "credits",
    ),
    OracleProductEvent.READING_REOPENED.value: _oracle_properties(
        "reading_id", "persona_code", "access_level"
    ),
    OracleProductEvent.READING_FAILED.value: _oracle_properties(
        "reading_id",
        "persona_code",
        "topic_code",
        "engine_version",
        "prompt_version",
        "schema_version",
        "attempt_count",
        "repair_used",
        "failure_code",
    ),
    OracleProductEvent.BIRTH_PROFILE_CONSENT_GRANTED.value: _oracle_properties(
        "consent_version"
    ),
    OracleProductEvent.BIRTH_PROFILE_CONSENT_REVOKED.value: _oracle_properties(
        "consent_version"
    ),
    OracleProductEvent.BIRTH_PROFILE_SAVED.value: _oracle_properties(
        "profile_version", "time_precision"
    ),
    OracleProductEvent.BIRTH_PROFILE_DELETED.value: _oracle_properties("profile_version"),
    OracleProductEvent.ASTROLOGY_CALCULATION_COMPLETED.value: _oracle_properties(
        "scope_code",
        "chart_schema_version",
        "engine_version",
        "time_precision",
        "house_system",
    ),
    OracleProductEvent.ASTROLOGY_CALCULATION_FAILED.value: _oracle_properties(
        "scope_code", "engine_version", "failure_code"
    ),
    OracleProductEvent.MEMORY_CONSENT_GRANTED.value: _oracle_properties("consent_version"),
    OracleProductEvent.MEMORY_CONSENT_REVOKED.value: _oracle_properties("consent_version"),
    OracleProductEvent.MEMORY_ITEM_CREATED.value: _oracle_properties(
        "memory_item_id", "memory_kind", "claim_basis", "source_type"
    ),
    OracleProductEvent.MEMORY_ITEM_DELETED.value: _oracle_properties(
        "memory_item_id", "memory_kind", "source_type"
    ),
    OracleProductEvent.MEMORY_ITEM_CORRECTED.value: _oracle_properties(
        "memory_item_id", "memory_kind", "claim_basis", "source_type"
    ),
    OracleProductEvent.MEMORY_CLEARED.value: _oracle_properties("deleted_count"),
    OracleProductEvent.MEMORY_CONTEXT_USED.value: _oracle_properties(
        "reading_id",
        "selected_count",
        "user_stated_count",
        "model_inferred_count",
    ),
    OracleProductEvent.MEMORY_EXTRACTION_COMPLETED.value: _oracle_properties(
        "reading_id", "persona_code", "created_count", "skipped_count"
    ),
    OracleProductEvent.MEMORY_EXTRACTION_SKIPPED.value: _oracle_properties(
        "reading_id", "persona_code", "outcome_code"
    ),
    OracleProductEvent.MEMORY_EXTRACTION_FAILED.value: _oracle_properties(
        "reading_id", "persona_code", "failure_code"
    ),
    OracleProductEvent.READING_FOLLOWUP_REQUESTED.value: _oracle_properties(
        "reading_id", "followup_version"
    ),
    OracleProductEvent.READING_FOLLOWUP_COMPLETED.value: _oracle_properties(
        "reading_id", "followup_version"
    ),
    OracleProductEvent.READING_FOLLOWUP_FAILED.value: _oracle_properties(
        "reading_id", "followup_version", "failure_code"
    ),
    OracleProductEvent.SHARE_PREVIEWED.value: _oracle_properties(
        "reading_id", "share_format", "renderer_version"
    ),
    OracleProductEvent.SHARE_CONFIRMED.value: _oracle_properties(
        "reading_id", "share_format", "renderer_version"
    ),
    OracleProductEvent.SAFETY_INPUT_CLASSIFIED.value: _oracle_properties(
        "persona_code", "stage_code", "action_code", "category_codes"
    ),
    OracleProductEvent.SAFETY_OUTPUT_REJECTED.value: _oracle_properties(
        "reading_id",
        "persona_code",
        "validator_version",
        "category_codes",
        "repair_used",
    ),
}

_ORACLE_REQUIRED: dict[str, frozenset[str]] = {
    OracleProductEvent.PERSONA_SELECTED.value: frozenset(
        {"event_version", "persona_code", "topic_code"}
    ),
    OracleProductEvent.READING_STARTED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "topic_code"}
    ),
    OracleProductEvent.READING_PREVIEW_READY.value: frozenset(
        {"event_version", "reading_id", "persona_code", "topic_code"}
    ),
    OracleProductEvent.READING_FULL_UNLOCKED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "product_code"}
    ),
    OracleProductEvent.READING_REOPENED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "access_level"}
    ),
    OracleProductEvent.READING_FAILED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "failure_code"}
    ),
    OracleProductEvent.BIRTH_PROFILE_CONSENT_GRANTED.value: frozenset(
        {"event_version", "consent_version"}
    ),
    OracleProductEvent.BIRTH_PROFILE_CONSENT_REVOKED.value: frozenset(
        {"event_version", "consent_version"}
    ),
    OracleProductEvent.BIRTH_PROFILE_SAVED.value: frozenset(
        {"event_version", "profile_version", "time_precision"}
    ),
    OracleProductEvent.BIRTH_PROFILE_DELETED.value: frozenset(
        {"event_version", "profile_version"}
    ),
    OracleProductEvent.ASTROLOGY_CALCULATION_COMPLETED.value: frozenset(
        {
            "event_version",
            "scope_code",
            "chart_schema_version",
            "engine_version",
            "time_precision",
        }
    ),
    OracleProductEvent.ASTROLOGY_CALCULATION_FAILED.value: frozenset(
        {"event_version", "scope_code", "engine_version", "failure_code"}
    ),
    OracleProductEvent.MEMORY_CONSENT_GRANTED.value: frozenset(
        {"event_version", "consent_version"}
    ),
    OracleProductEvent.MEMORY_CONSENT_REVOKED.value: frozenset(
        {"event_version", "consent_version"}
    ),
    OracleProductEvent.MEMORY_ITEM_CREATED.value: frozenset(
        {
            "event_version",
            "memory_item_id",
            "memory_kind",
            "claim_basis",
            "source_type",
        }
    ),
    OracleProductEvent.MEMORY_ITEM_DELETED.value: frozenset(
        {"event_version", "memory_item_id", "memory_kind", "source_type"}
    ),
    OracleProductEvent.MEMORY_ITEM_CORRECTED.value: frozenset(
        {
            "event_version",
            "memory_item_id",
            "memory_kind",
            "claim_basis",
            "source_type",
        }
    ),
    OracleProductEvent.MEMORY_CLEARED.value: frozenset(
        {"event_version", "deleted_count"}
    ),
    OracleProductEvent.MEMORY_CONTEXT_USED.value: frozenset(
        {"event_version", "reading_id", "selected_count"}
    ),
    OracleProductEvent.MEMORY_EXTRACTION_COMPLETED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "created_count"}
    ),
    OracleProductEvent.MEMORY_EXTRACTION_SKIPPED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "outcome_code"}
    ),
    OracleProductEvent.MEMORY_EXTRACTION_FAILED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "failure_code"}
    ),
    OracleProductEvent.READING_FOLLOWUP_REQUESTED.value: frozenset(
        {"event_version", "reading_id", "followup_version"}
    ),
    OracleProductEvent.READING_FOLLOWUP_COMPLETED.value: frozenset(
        {"event_version", "reading_id", "followup_version"}
    ),
    OracleProductEvent.READING_FOLLOWUP_FAILED.value: frozenset(
        {"event_version", "reading_id", "followup_version", "failure_code"}
    ),
    OracleProductEvent.SHARE_PREVIEWED.value: frozenset(
        {"event_version", "reading_id", "share_format", "renderer_version"}
    ),
    OracleProductEvent.SHARE_CONFIRMED.value: frozenset(
        {"event_version", "reading_id", "share_format", "renderer_version"}
    ),
    OracleProductEvent.SAFETY_INPUT_CLASSIFIED.value: frozenset(
        {"event_version", "persona_code", "stage_code", "action_code"}
    ),
    OracleProductEvent.SAFETY_OUTPUT_REJECTED.value: frozenset(
        {"event_version", "reading_id", "persona_code", "validator_version"}
    ),
}

_EVENT_SCOPES: dict[str, EventScope] = {
    "bot_started": EventScope.USER,
    "age_confirmed": EventScope.USER,
    "consent_accepted": EventScope.USER,
    "onboarding_completed": EventScope.USER,
    "analysis_started": EventScope.ANALYSIS,
    "conversation_submitted": EventScope.ANALYSIS,
    "conversation_parsed": EventScope.ANALYSIS,
    "analysis_context_completed": EventScope.ANALYSIS,
    "analysis_cancelled": EventScope.ANALYSIS,
    "preview_viewed": EventScope.ANALYSIS,
    "paywall_viewed": EventScope.ANALYSIS,
    "credit_spent": EventScope.ANALYSIS,
    "credit_refunded": EventScope.ANALYSIS,
    "analysis_processing_started": EventScope.ANALYSIS,
    "analysis_completed": EventScope.ANALYSIS,
    "analysis_failed": EventScope.ANALYSIS,
    "analysis_feedback_submitted": EventScope.ANALYSIS,
    "analysis_deleted": EventScope.ANALYSIS,
    "checkout_started": EventScope.ORDER,
    "purchase_completed": EventScope.ORDER,
    "payment_failed": EventScope.ORDER,
    "all_data_deleted": EventScope.ACCOUNT,
    "main_menu_opened": EventScope.ACTION,
    "conversation_rejected": EventScope.ACTION,
    "analysis_history_opened": EventScope.ACTION,
    "analysis_report_delivered": EventScope.ACTION,
    "reply_suggestions_requested": EventScope.ACTION,
    "followup_requested": EventScope.ACTION,
    OracleProductEvent.PERSONA_SELECTED.value: EventScope.ACTION,
    OracleProductEvent.READING_STARTED.value: EventScope.READING,
    OracleProductEvent.READING_PREVIEW_READY.value: EventScope.READING,
    OracleProductEvent.READING_FULL_UNLOCKED.value: EventScope.READING,
    OracleProductEvent.READING_REOPENED.value: EventScope.ACTION,
    OracleProductEvent.READING_FAILED.value: EventScope.READING,
    OracleProductEvent.BIRTH_PROFILE_CONSENT_GRANTED.value: EventScope.ACTION,
    OracleProductEvent.BIRTH_PROFILE_CONSENT_REVOKED.value: EventScope.ACTION,
    OracleProductEvent.BIRTH_PROFILE_SAVED.value: EventScope.ACTION,
    OracleProductEvent.BIRTH_PROFILE_DELETED.value: EventScope.ACTION,
    OracleProductEvent.ASTROLOGY_CALCULATION_COMPLETED.value: EventScope.ACTION,
    OracleProductEvent.ASTROLOGY_CALCULATION_FAILED.value: EventScope.ACTION,
    OracleProductEvent.MEMORY_CONSENT_GRANTED.value: EventScope.ACTION,
    OracleProductEvent.MEMORY_CONSENT_REVOKED.value: EventScope.ACTION,
    OracleProductEvent.MEMORY_ITEM_CREATED.value: EventScope.MEMORY_ITEM,
    OracleProductEvent.MEMORY_ITEM_DELETED.value: EventScope.MEMORY_ITEM,
    OracleProductEvent.MEMORY_ITEM_CORRECTED.value: EventScope.MEMORY_ITEM,
    OracleProductEvent.MEMORY_CLEARED.value: EventScope.ACTION,
    OracleProductEvent.MEMORY_CONTEXT_USED.value: EventScope.READING,
    OracleProductEvent.MEMORY_EXTRACTION_COMPLETED.value: EventScope.READING,
    OracleProductEvent.MEMORY_EXTRACTION_SKIPPED.value: EventScope.READING,
    OracleProductEvent.MEMORY_EXTRACTION_FAILED.value: EventScope.READING,
    OracleProductEvent.READING_FOLLOWUP_REQUESTED.value: EventScope.READING,
    OracleProductEvent.READING_FOLLOWUP_COMPLETED.value: EventScope.READING,
    OracleProductEvent.READING_FOLLOWUP_FAILED.value: EventScope.READING,
    OracleProductEvent.SHARE_PREVIEWED.value: EventScope.ACTION,
    OracleProductEvent.SHARE_CONFIRMED.value: EventScope.ACTION,
    OracleProductEvent.SAFETY_INPUT_CLASSIFIED.value: EventScope.ACTION,
    OracleProductEvent.SAFETY_OUTPUT_REJECTED.value: EventScope.READING,
}


class AnalyticsContractError(ValueError):
    """A generic error that never echoes rejected names or values."""

    def __init__(self) -> None:
        super().__init__("analytics event violates the safe contract")


class AnalyticsClient(Protocol):
    """Track allow-listed lifecycle data, never user message content."""

    async def track(
        self, user_id: str | None, event: str, properties: Mapping[str, str] | None = None
    ) -> None: ...


class NoOpAnalyticsClient:
    """Disabled analytics implementation."""

    async def track(
        self, user_id: str | None, event: str, properties: Mapping[str, str] | None = None
    ) -> None:
        return None


class DiscardingAnalyticsClient:
    """Explicit sink used only when analytics is intentionally disabled."""

    async def track(
        self, user_id: str | None, event: str, properties: Mapping[str, str] | None = None
    ) -> None:
        logger.info("analytics_event_intentionally_discarded event=%s", event)


class ResilientAnalyticsClient:
    """Keep analytics failures outside already committed business transitions."""

    def __init__(self, inner: AnalyticsClient) -> None:
        self._inner = inner

    async def track(
        self, user_id: str | None, event: str, properties: Mapping[str, str] | None = None
    ) -> None:
        try:
            await self._inner.track(user_id, event, properties)
        except Exception:
            logger.warning("analytics_delivery_failed event=%s", _safe_event_for_log(event))


def validate_event_properties(event: str, properties: Mapping[str, str] | None) -> dict[str, str]:
    """Return a validated copy containing only short, structured metadata."""

    allowed = _EVENT_PROPERTIES.get(event)
    if allowed is None:
        raise AnalyticsContractError
    supplied = dict(properties or {})
    required = _ORACLE_REQUIRED.get(event, frozenset())
    if not required <= supplied.keys() or not supplied.keys() <= allowed:
        raise AnalyticsContractError
    for key, value in supplied.items():
        if not isinstance(value, str) or not value or len(value) > 128 or not value.isprintable():
            raise AnalyticsContractError
        if key in _UUID_KEYS:
            try:
                UUID(value)
            except ValueError:
                raise AnalyticsContractError from None
        elif key in _INTEGER_KEYS:
            try:
                int(value)
            except ValueError:
                raise AnalyticsContractError from None
        elif _SAFE_VALUE.fullmatch(value) is None:
            raise AnalyticsContractError
    if event in _ORACLE_REQUIRED and supplied.get("event_version") != PRODUCT_EVENT_TAXONOMY_VERSION:
        raise AnalyticsContractError
    return supplied


def event_scope(event: str) -> EventScope:
    """Return the configured idempotency scope for a known event."""

    try:
        return _EVENT_SCOPES[event]
    except KeyError:
        raise AnalyticsContractError from None


def event_identity(
    user_id: str | None,
    event: str,
    properties: Mapping[str, str],
    correlation_id: str,
) -> tuple[str | None, str]:
    """Return pseudonymous subject and deterministic transition idempotency key."""

    scope = event_scope(event)
    subject = _validated_optional_uuid(user_id)
    if scope is EventScope.USER:
        identity = subject
    elif scope is EventScope.ANALYSIS:
        identity = properties.get("analysis_id")
    elif scope is EventScope.READING:
        identity = properties.get("reading_id")
    elif scope is EventScope.ORDER:
        identity = properties.get("order_id")
    elif scope is EventScope.MEMORY_ITEM:
        identity = properties.get("memory_item_id")
    elif scope is EventScope.ACCOUNT:
        identity = properties.get("user_id")
    else:
        identity = correlation_id
    if identity is None:
        raise AnalyticsContractError
    return subject, f"{event}:{identity}"


def event_taxonomy_version(event: str) -> str:
    """Expose the immutable schema family for downstream warehouse transforms."""

    if event in _ORACLE_REQUIRED:
        return PRODUCT_EVENT_TAXONOMY_VERSION
    if event in _EVENT_PROPERTIES:
        return LEGACY_EVENT_TAXONOMY_VERSION
    raise AnalyticsContractError


def known_event_names() -> tuple[str, ...]:
    """Expose a stable ordered list for admin funnel aggregation and tests."""

    return tuple(_EVENT_PROPERTIES)


def _validated_optional_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        raise AnalyticsContractError from None


def _safe_event_for_log(event: str) -> str:
    return event if event in _EVENT_PROPERTIES else "unknown"
