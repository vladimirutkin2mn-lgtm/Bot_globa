"""Task 06 bridge: skip the missing-profile interstitial in Astro Duel."""

# ruff: noqa: PLW0603

from collections.abc import Awaitable, Callable
from html import escape

from aiogram import Bot
from aiogram.types import Message

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_viral_upgrade as viral_upgrade
from app.domain.natal_chart import NatalChartResult
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService

_INSTALL_MARKERS: set[str] = set()
_PREVIOUS_DUEL: Callable[..., Awaitable[None]] | None = None


def duel_sign_state(
    first_chart: NatalChartResult | None,
    second_chart: NatalChartResult | None,
) -> tuple[tuple[str, str], int]:
    """Return known sun signs and the first participant who still must self-identify."""

    signs = (viral_upgrade._sign_token(first_chart), viral_upgrade._sign_token(second_chart))
    if signs[0] == "x":
        return signs, 0
    if signs[1] == "x":
        return signs, 1
    raise ValueError("duel sign intake requires a missing natal chart")


async def _duel_cjm(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    profiles: BirthProfileService,
    first_id: int,
    second_id: int,
) -> None:
    """Use the precise duel when possible; otherwise ask for the first missing sign now."""

    first_chart = await compatibility._chart_for(first_id, onboarding, profiles)
    second_chart = await compatibility._chart_for(second_id, onboarding, profiles)
    if first_chart is not None and second_chart is not None:
        assert _PREVIOUS_DUEL is not None
        await _PREVIOUS_DUEL(
            message,
            bot,
            onboarding,
            profiles,
            first_id,
            second_id,
        )
        return

    signs, slot = duel_sign_state(first_chart, second_chart)
    expected_id = first_id if slot == 0 else second_id
    expected_name = await compatibility._member_name(bot, message, expected_id)
    await message.edit_text(
        f"☀️ <b>{escape(expected_name)}, выбери свой знак</b>\n\n"
        "Начинаем быстрый режим Астро-дуэли сразу. Натальную карту можно добавить потом.",
        reply_markup=viral_upgrade._sign_keyboard(
            "d",
            first_id,
            second_id,
            signs,
            slot,
        ),
    )


def install_group_duel_cjm() -> None:
    """Patch the live duel renderer once, after the legacy viral layers are installed."""

    global _PREVIOUS_DUEL

    if "group_duel_cjm" in _INSTALL_MARKERS:
        return
    _PREVIOUS_DUEL = viral_upgrade._duel_v2
    viral_upgrade._duel_v2 = _duel_cjm
    _INSTALL_MARKERS.add("group_duel_cjm")
