"""The contract a Telegram intake registers with the crisis-handoff middleware.

Kept dependency-free so both the flow definitions and the middleware can import it
without a cycle.
"""

from collections.abc import Callable
from dataclasses import dataclass

from aiogram.fsm.state import State
from aiogram.types import InlineKeyboardMarkup


@dataclass(frozen=True, slots=True)
class SafetyIntake:
    """One flow's question/context surface and the keyboard its handoff may offer."""

    persona_code: str
    question_state: str
    context_state: str
    skip_context_callback: str
    handoff_keyboard: Callable[[], InlineKeyboardMarkup]


def state_name(state: State) -> str:
    """aiogram types `State.state` as optional; a declared group member always has one."""
    name = state.state
    if name is None:
        raise RuntimeError("reading state group member has no state name")
    return name
