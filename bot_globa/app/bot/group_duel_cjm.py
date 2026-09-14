"""Task 06 bridge: keep Astro Duel short and route its private CTA correctly."""

# ruff: noqa: PLW0603

from collections.abc import Awaitable, Callable
from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_social_handlers, group_viral_upgrade as viral_upgrade
from app.domain.natal_chart import NatalChartResult
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService

_INSTALL_MARKERS: set[str] = set()
_PREVIOUS_DUEL: Callable[..., Awaitable[None]] | None = None
_PREVIOUS_PARTY_BACK: Callable[..., InlineKeyboardMarkup] | None = None
_DUEL_LEGACY_RESULT_LABEL = "💞 Проверить совместимость"


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


def _party_back_cjm(
    username: str | None,
    label: str = "🔮 Что сегодня про меня?",
) -> InlineKeyboardMarkup:
    """Fix the legacy duel footer without changing unrelated group-game footers."""

    if label != _DUEL_LEGACY_RESULT_LABEL:
        assert _PREVIOUS_PARTY_BACK is not None
        return _PREVIOUS_PARTY_BACK(username, label)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪐 Разобрать дуэль лично",
                    callback_data="p108:private:duel:astro",
                )
            ],
            [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
        ]
    )


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
    """Patch the live duel renderer and its legacy private footer exactly once."""

    global _PREVIOUS_DUEL, _PREVIOUS_PARTY_BACK

    if "group_duel_cjm" in _INSTALL_MARKERS:
        return
    _PREVIOUS_DUEL = viral_upgrade._duel_v2
    viral_upgrade._duel_v2 = _duel_cjm
    _PREVIOUS_PARTY_BACK = group_social_handlers._party_back
    group_social_handlers._party_back = _party_back_cjm
    _INSTALL_MARKERS.add("group_duel_cjm")
