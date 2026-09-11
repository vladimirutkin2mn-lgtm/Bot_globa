"""Translate successful Telegram actions into privacy-safe Numa acquisition signals.

Telegram identifiers are used only transiently to resolve an internal user and to derive
an opaque idempotency UUID. They are never emitted as analytics properties.
"""

from dataclasses import dataclass, replace
from uuid import UUID, uuid5

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.domain.conversion_experiment import free_preview_experiment_assignment
from app.observability.context import current_correlation_id
from app.providers.numa_product_analytics import ProductFlow, ProductSource
from app.services.numa_product_analytics import ProductAttribution

_RUNTIME_NAMESPACE = UUID("87e9d297-0ca6-4b8c-a8c3-83915c7ec559")
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_FREE_PREVIEW_SCENARIOS = frozenset(
    {
        "personal_oracle_v1",
        "tarot_reader_v1",
        "love_oracle_v1",
        "mystical_psychologist_v1",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeProductSignal:
    """One successful runtime action before analytics persistence."""

    telegram_user_id: int | None
    event_key: str
    attribution: ProductAttribution


def runtime_signal(event: TelegramObject) -> RuntimeProductSignal | None:
    """Classify only explicit product actions; ordinary chat text is ignored."""

    update = event if isinstance(event, Update) else None
    callback = update.callback_query if update is not None else _callback(event)
    message = update.message if update is not None else _message(event)
    event_key = _event_key(update)

    if callback is not None:
        signal = _callback_signal(callback, event_key)
        if signal is not None:
            return signal
    if message is not None and message.chat.type in _GROUP_TYPES:
        return _group_command_signal(message, event_key)
    return None


def runtime_entity_id(signal: RuntimeProductSignal, internal_user_id: UUID | None) -> UUID:
    """Derive a retry-stable opaque UUID without persisting Telegram identifiers."""

    namespace = internal_user_id or _RUNTIME_NAMESPACE
    return uuid5(namespace, f"numa-runtime:{signal.event_key}")


def runtime_attribution_for_user(
    signal: RuntimeProductSignal,
    internal_user_id: UUID | None,
) -> ProductAttribution:
    """Attach the stable free-preview arm without changing acquisition source."""

    attribution = signal.attribution
    if (
        internal_user_id is None
        or attribution.flow is not ProductFlow.PERSONAL
        or attribution.scenario_version not in _FREE_PREVIEW_SCENARIOS
    ):
        return attribution
    return replace(
        attribution,
        experiment_assignment=free_preview_experiment_assignment(internal_user_id),
    )


def _callback_signal(callback: CallbackQuery, event_key: str) -> RuntimeProductSignal | None:
    data = callback.data or ""
    actor_id = callback.from_user.id
    personal_modes = {
        "oracle:auto": "personal_oracle_v1",
        "oracle:tarot": "tarot_reader_v1",
        "oracle:love": "love_oracle_v1",
        "oracle:astro": "astrologer_v1",
    }
    if data in personal_modes:
        return _signal(
            actor_id,
            event_key,
            ProductFlow.PERSONAL,
            ProductSource.NORMAL_START,
            personal_modes[data],
        )
    if data == "daily:personal":
        return _signal(
            actor_id,
            event_key,
            ProductFlow.PERSONAL,
            ProductSource.DAILY_HOROSCOPE,
            "personal_day_forecast_v1",
        )
    group_callbacks = (
        ("group:duel:", ProductSource.GROUP_DUEL, "group_duel_v1"),
        ("group:party:", ProductSource.GROUP_PARTY, "group_party_v2"),
        ("group:event:", ProductSource.GROUP_EVENT, "group_event_v1"),
    )
    for prefix, source, scenario in group_callbacks:
        if data.startswith(prefix):
            return _signal(actor_id, event_key, ProductFlow.GROUP, source, scenario)
    return None


def _group_command_signal(message: Message, event_key: str) -> RuntimeProductSignal | None:
    text = message.text or ""
    command = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].casefold()
    commands = {
        "/card": (ProductSource.GROUP_CARD, "group_card_v1"),
        "/compatibility": (ProductSource.GROUP_COMPATIBILITY, "group_compatibility_v1"),
        "/party": (ProductSource.GROUP_PARTY, "group_party_v2"),
        "/event": (ProductSource.GROUP_EVENT, "group_event_v1"),
        "/chat": (ProductSource.GROUP_CHAT, "group_chat_archetype_v1"),
    }
    configured = commands.get(command)
    if configured is None:
        return None
    source, scenario = configured
    actor_id = message.from_user.id if message.from_user is not None else None
    return _signal(actor_id, event_key, ProductFlow.GROUP, source, scenario)


def _signal(
    telegram_user_id: int | None,
    event_key: str,
    flow: ProductFlow,
    source: ProductSource,
    scenario_version: str,
) -> RuntimeProductSignal:
    return RuntimeProductSignal(
        telegram_user_id=telegram_user_id,
        event_key=event_key,
        attribution=ProductAttribution(
            flow=flow,
            source=source,
            scenario_version=scenario_version,
        ),
    )


def _event_key(update: Update | None) -> str:
    if update is not None:
        return f"telegram-update-{update.update_id}"
    return current_correlation_id()


def _callback(event: TelegramObject) -> CallbackQuery | None:
    return event if isinstance(event, CallbackQuery) else None


def _message(event: TelegramObject) -> Message | None:
    return event if isinstance(event, Message) else None
