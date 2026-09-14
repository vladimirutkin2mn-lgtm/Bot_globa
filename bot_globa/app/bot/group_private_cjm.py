"""Task 06: preserve the originating group game when moving to private chat."""

# ruff: noqa: PLW0603

from collections.abc import Callable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import group_cjm_v3
from app.domain.synastry import CompatibilityContext

_INSTALL_MARKERS: set[str] = set()
_PREVIOUS_PRECISION_KEYBOARD: Callable[..., InlineKeyboardMarkup] | None = None


def _precision_keyboard_with_private(
    username: str | None,
    *,
    context: CompatibilityContext,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
) -> InlineKeyboardMarkup:
    """Add one tracked personal continuation without removing precision controls."""

    assert _PREVIOUS_PRECISION_KEYBOARD is not None
    current = _PREVIOUS_PRECISION_KEYBOARD(
        username,
        context=context,
        first_id=first_id,
        second_id=second_id,
        first_name=first_name,
        second_name=second_name,
    )
    target = "love" if context is CompatibilityContext.LOVE else "astro"
    label = "💞 Разобрать отношения лично" if target == "love" else "🪐 Разобрать лично"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"p108:private:compatibility:{target}",
                )
            ],
            *[list(row) for row in current.inline_keyboard],
        ]
    )


def install_group_private_cjm() -> None:
    """Patch the quick compatibility footer once after the Task 06 renderer is installed."""

    global _PREVIOUS_PRECISION_KEYBOARD

    if "group_private_cjm" in _INSTALL_MARKERS:
        return
    _PREVIOUS_PRECISION_KEYBOARD = group_cjm_v3._precision_keyboard
    group_cjm_v3._precision_keyboard = _precision_keyboard_with_private
    _INSTALL_MARKERS.add("group_private_cjm")
