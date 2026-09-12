"""Request-local outcome signal for the Numa reading funnel.

Only internal UUIDs and a short outcome code are stored in the context. The
signal never contains Telegram identifiers, question/result text or payment
secrets.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ReadingFunnelOutcome(StrEnum):
    OFFER_SHOWN = "offer_shown"
    PAYWALL_REQUIRED = "paywall_required"
    FULL_UNLOCKED = "full_unlocked"


@dataclass(frozen=True, slots=True)
class ReadingFunnelSignal:
    outcome: ReadingFunnelOutcome
    reading_id: UUID
    user_id: UUID


_current_signal: ContextVar[ReadingFunnelSignal | None] = ContextVar(
    "numa_reading_funnel_signal",
    default=None,
)


def clear_reading_funnel_signal() -> None:
    _current_signal.set(None)


def record_reading_funnel_signal(
    outcome: ReadingFunnelOutcome,
    reading_id: UUID,
    user_id: UUID,
) -> None:
    _current_signal.set(ReadingFunnelSignal(outcome, reading_id, user_id))


def consume_reading_funnel_signal() -> ReadingFunnelSignal | None:
    signal = _current_signal.get()
    _current_signal.set(None)
    return signal
