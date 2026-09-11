"""P1-08 group growth bridge over the existing privacy-safe game mechanics.

The upgrade deliberately adds no member discovery or chat-message ingestion. People
join games through existing callbacks, choose their own sign, and may upgrade to a
private natal flow later. Group funnel analytics is anonymous and code-only.
"""

# ruff: noqa: PLW0603

from collections.abc import Awaitable, Callable

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import core_handlers, group_handlers
from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_viral_upgrade as viral_upgrade
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.domain.natal_chart import NatalChartResult
from app.domain.synastry import CompatibilityContext
from app.providers.analytics import AnalyticsClient
from app.providers.numa_product_analytics import (
    GROUP_FUNNEL_SOURCE,
    GROUP_GAME_CODES,
    GroupFunnelEvent,
)
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService

_INSTALL_MARKERS: set[str] = set()
_PREVIOUS_MORE_MENU: Callable[[], InlineKeyboardMarkup] | None = None
_PREVIOUS_COMPATIBILITY_RENDER: Callable[..., Awaitable[None]] | None = None
_PREVIOUS_COMPATIBILITY_ACTION: Callable[..., Awaitable[None]] | None = None
_PREVIOUS_VIRAL_ACTION: Callable[..., Awaitable[None]] | None = None
_PREVIOUS_FALLBACK_KEYBOARD: Callable[..., InlineKeyboardMarkup] | None = None
_PREVIOUS_UPGRADE_KEYBOARD: Callable[..., InlineKeyboardMarkup] | None = None
_PREVIOUS_RESULT_KEYBOARD: Callable[..., InlineKeyboardMarkup] | None = None


def _friends_intro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить Numa в группу", callback_data="friends:add")],
            [InlineKeyboardButton(text="← Назад", callback_data="menu:more")],
        ]
    )


def _friends_add_keyboard(username: str) -> InlineKeyboardMarkup:
    clean_username = username.removeprefix("@")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Выбрать группу",
                    url=f"https://t.me/{clean_username}?startgroup=party",
                )
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="menu:friends")],
        ]
    )


def _more_menu_with_friends() -> InlineKeyboardMarkup:
    assert _PREVIOUS_MORE_MENU is not None
    current = _PREVIOUS_MORE_MENU()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Играть с друзьями", callback_data="menu:friends")],
            *[list(row) for row in current.inline_keyboard],
        ]
    )


async def _track_group(
    analytics: AnalyticsClient,
    event: GroupFunnelEvent,
    *,
    game: str | None = None,
) -> None:
    properties = {"source": GROUP_FUNNEL_SOURCE}
    if game is not None:
        properties["game"] = game
    await analytics.track(None, event.value, properties)


async def friends_entry(
    callback: CallbackQuery,
    state: FSMContext,
    analytics: AnalyticsClient,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await _track_group(analytics, GroupFunnelEvent.ENTRY_OPENED)
    await show_screen(
        callback.message,
        Scene.MAIN_MENU,
        "🎲 <b>Играть с друзьями</b>\n\n"
        "Добавь Numa в групповой чат и запускай совместимость или Астро-дуэль. "
        "Натальная карта не обязательна: в быстром режиме каждый участник сам "
        "подтверждает свой знак.\n\n"
        "Права администратора для этих игр не нужны.",
        reply_markup=_friends_intro_keyboard(),
        state=state,
    )


async def friends_add(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    analytics: AnalyticsClient,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    me = await bot.get_me()
    if not me.username:
        await callback.message.answer("Не удалось получить имя Numa. Попробуйте ещё раз.")
        return
    await _track_group(analytics, GroupFunnelEvent.ADD_STARTED)
    await show_screen(
        callback.message,
        Scene.MAIN_MENU,
        "✨ <b>Выбери групповой чат</b>\n\n"
        "После добавления Numa покажет короткое меню. Начать можно с "
        "«Совместимости» или «Астро-дуэли». Участники подтверждают себя кнопками — "
        "обычные сообщения чата для игры не нужны.",
        reply_markup=_friends_add_keyboard(me.username),
        state=state,
    )


async def group_added(message: Message, bot: Bot) -> None:
    """Show one compact onboarding when Numa itself is added to a group."""

    members = message.new_chat_members or []
    if not members:
        return
    me = await bot.get_me()
    if all(member.id != me.id for member in members):
        return
    await message.answer(
        "✨ <b>Numa в группе</b>\n\n"
        "Начните с 💞 /compatibility или ⚔️ /duel. Натальная карта не обязательна: "
        "если её нет, каждый участник сам выберет свой знак.\n\n"
        "Numa работает через команды и кнопки — читать обычную переписку для игр не нужно.",
        reply_markup=group_handlers._party_menu_keyboard(),
    )


def _private_tracking_keyboard(
    keyboard: InlineKeyboardMarkup,
    *,
    game: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in keyboard.inline_keyboard:
        mapped: list[InlineKeyboardButton] = []
        for button in row:
            target: str | None = None
            if button.url and "?start=astro" in button.url:
                target = "astro"
            elif button.url and "?start=love" in button.url:
                target = "love"
            if target is None:
                mapped.append(button)
            else:
                mapped.append(
                    InlineKeyboardButton(
                        text=button.text,
                        callback_data=f"p108:private:{game}:{target}",
                    )
                )
        rows.append(mapped)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fallback_keyboard_p1_08(
    username: str | None,
    *,
    mode: str,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
    first_chart: NatalChartResult | None,
    second_chart: NatalChartResult | None,
) -> InlineKeyboardMarkup:
    assert _PREVIOUS_FALLBACK_KEYBOARD is not None
    keyboard = _PREVIOUS_FALLBACK_KEYBOARD(
        username,
        mode=mode,
        first_id=first_id,
        second_id=second_id,
        first_name=first_name,
        second_name=second_name,
        first_chart=first_chart,
        second_chart=second_chart,
    )
    return _private_tracking_keyboard(
        keyboard,
        game="compatibility" if mode == "c" else "duel",
    )


def _upgrade_keyboard_p1_08(
    username: str | None,
    *,
    mode: str,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
) -> InlineKeyboardMarkup:
    assert _PREVIOUS_UPGRADE_KEYBOARD is not None
    keyboard = _PREVIOUS_UPGRADE_KEYBOARD(
        username,
        mode=mode,
        first_id=first_id,
        second_id=second_id,
        first_name=first_name,
        second_name=second_name,
    )
    return _private_tracking_keyboard(
        keyboard,
        game="compatibility" if mode == "c" else "duel",
    )


def _compatibility_result_keyboard_p1_08(
    bot_username: str | None,
    inviter_id: int,
    first_id: int,
    second_id: int,
) -> InlineKeyboardMarkup:
    assert _PREVIOUS_RESULT_KEYBOARD is not None
    keyboard = _PREVIOUS_RESULT_KEYBOARD(bot_username, inviter_id, first_id, second_id)
    return _private_tracking_keyboard(keyboard, game="compatibility")


async def group_to_private(
    callback: CallbackQuery,
    bot: Bot,
    analytics: AnalyticsClient,
) -> None:
    data = callback.data or ""
    parts = data.split(":")
    if len(parts) != 4 or parts[:2] != ["p108", "private"]:
        await callback.answer()
        return
    game, target = parts[2], parts[3]
    if game not in GROUP_GAME_CODES or target not in {"astro", "love"}:
        await callback.answer("Не получилось открыть личный сценарий.")
        return
    await _track_group(analytics, GroupFunnelEvent.TO_PRIVATE_CLICKED, game=game)
    me = await bot.get_me()
    if not me.username:
        await callback.answer("Не удалось открыть личный чат.")
        return
    clean_username = me.username.removeprefix("@")
    await callback.answer("Открой Numa в личке ✨")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "✨ Продолжение — только между тобой и Numa.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Открыть Numa",
                            url=f"https://t.me/{clean_username}?start={target}",
                        )
                    ]
                ]
            ),
        )


async def _render_compatibility_p1_08(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    *,
    context: CompatibilityContext,
    inviter_id: int,
    first_id: int,
    second_id: int,
) -> None:
    """Use the existing sign flow when natal profiles are unavailable."""

    first_name, second_name = await compatibility._pair_names(
        bot,
        message,
        first_id,
        second_id,
    )
    first_chart = await compatibility._chart_for(first_id, onboarding, birth_profile_service)
    second_chart = await compatibility._chart_for(second_id, onboarding, birth_profile_service)
    if first_chart is None or second_chart is None:
        await viral_upgrade._missing_screen(
            message,
            bot,
            mode="c",
            first_id=first_id,
            second_id=second_id,
            first_name=first_name,
            second_name=second_name,
            first_chart=first_chart,
            second_chart=second_chart,
        )
        return
    assert _PREVIOUS_COMPATIBILITY_RENDER is not None
    await _PREVIOUS_COMPATIBILITY_RENDER(
        message,
        bot,
        onboarding,
        birth_profile_service,
        context=context,
        inviter_id=inviter_id,
        first_id=first_id,
        second_id=second_id,
    )


def _compatibility_context_ids(data: str | None) -> tuple[int, int] | None:
    if data is None:
        return None
    parts = data.split(":")
    if len(parts) != 6 or parts[:2] != ["gc", "c"]:
        return None
    try:
        return int(parts[4]), int(parts[5])
    except ValueError:
        return None


async def compatibility_action_p1_08(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    analytics: AnalyticsClient,
) -> None:
    """Add anonymous start/completion telemetry around the existing compatibility action."""

    ids = _compatibility_context_ids(callback.data)
    full_ready = False
    if ids is not None:
        first_id, second_id = ids
        first_chart = await compatibility._chart_for(first_id, onboarding, birth_profile_service)
        second_chart = await compatibility._chart_for(second_id, onboarding, birth_profile_service)
        full_ready = first_chart is not None and second_chart is not None
        await _track_group(
            analytics,
            GroupFunnelEvent.GAME_STARTED,
            game="compatibility",
        )
    assert _PREVIOUS_COMPATIBILITY_ACTION is not None
    await _PREVIOUS_COMPATIBILITY_ACTION(
        callback,
        bot,
        state,
        onboarding,
        birth_profile_service,
    )
    if ids is not None and full_ready:
        await _track_group(
            analytics,
            GroupFunnelEvent.GAME_COMPLETED,
            game="compatibility",
        )


def _final_sign_game(callback: CallbackQuery) -> str | None:
    data = callback.data or ""
    parts = data.split(":")
    if len(parts) != 7 or parts[:2] != ["g2", "z"]:
        return None
    mode, pair, raw_signs, raw_slot, code = parts[2:]
    try:
        first_id, second_id = viral_upgrade._decode_pair(pair)
        signs = list(viral_upgrade._decode_signs(raw_signs))
        slot = int(raw_slot)
    except (TypeError, ValueError):
        return None
    if slot not in {0, 1} or code not in viral_upgrade._SIGN_BY_CODE:
        return None
    expected = first_id if slot == 0 else second_id
    if callback.from_user.id != expected:
        return None
    signs[slot] = code
    if "x" in signs:
        return None
    return "compatibility" if mode == "c" else "duel" if mode == "d" else None


def _duel_completed(callback: CallbackQuery) -> bool:
    data = callback.data or ""
    if data.startswith("g2:R:"):
        parts = data.split(":")
        if len(parts) != 5 or parts[4] != "2":
            return False
        try:
            first_id, second_id = viral_upgrade._decode_pair(parts[2])
        except (TypeError, ValueError):
            return False
        return callback.from_user.id in {first_id, second_id}
    if data.startswith("g2:r:"):
        parts = data.split(":")
        if len(parts) != 4 or parts[3] != "2":
            return False
        try:
            first_id, second_id = viral_upgrade._decode_pair(parts[2])
        except (TypeError, ValueError):
            return False
        return callback.from_user.id in {first_id, second_id}
    return False


async def viral_action_p1_08(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    analytics: AnalyticsClient,
) -> None:
    """Measure only aggregate game transitions around the existing P1 group engine."""

    data = callback.data or ""
    final_sign_game = _final_sign_game(callback)
    if data.startswith("v:d:"):
        await _track_group(analytics, GroupFunnelEvent.GAME_STARTED, game="duel")
    assert _PREVIOUS_VIRAL_ACTION is not None
    await _PREVIOUS_VIRAL_ACTION(
        callback,
        bot,
        onboarding,
        birth_profile_service,
    )
    if final_sign_game == "compatibility":
        await _track_group(
            analytics,
            GroupFunnelEvent.GAME_COMPLETED,
            game="compatibility",
        )
    if _duel_completed(callback):
        await _track_group(analytics, GroupFunnelEvent.GAME_COMPLETED, game="duel")


def install_group_p1_08() -> None:
    """Install the P1-08 UX bridge exactly once."""

    global _PREVIOUS_COMPATIBILITY_ACTION
    global _PREVIOUS_COMPATIBILITY_RENDER
    global _PREVIOUS_FALLBACK_KEYBOARD
    global _PREVIOUS_MORE_MENU
    global _PREVIOUS_RESULT_KEYBOARD
    global _PREVIOUS_UPGRADE_KEYBOARD
    global _PREVIOUS_VIRAL_ACTION

    if "group_p1_08" in _INSTALL_MARKERS:
        return

    _PREVIOUS_MORE_MENU = getattr(core_handlers, "more_menu_keyboard")
    setattr(core_handlers, "more_menu_keyboard", _more_menu_with_friends)

    _PREVIOUS_COMPATIBILITY_RENDER = compatibility._render_compatibility
    compatibility._render_compatibility = _render_compatibility_p1_08
    _PREVIOUS_RESULT_KEYBOARD = compatibility._result_keyboard
    compatibility._result_keyboard = _compatibility_result_keyboard_p1_08

    _PREVIOUS_FALLBACK_KEYBOARD = viral_upgrade._fallback_keyboard
    viral_upgrade._fallback_keyboard = _fallback_keyboard_p1_08
    _PREVIOUS_UPGRADE_KEYBOARD = viral_upgrade._upgrade_keyboard
    viral_upgrade._upgrade_keyboard = _upgrade_keyboard_p1_08

    group_router = group_handlers.router
    _PREVIOUS_COMPATIBILITY_ACTION = compatibility.compatibility_action
    group_router.callback_query.handlers[:] = [
        handler
        for handler in group_router.callback_query.handlers
        if handler.callback is not compatibility.compatibility_action
    ]
    group_router.callback_query(F.data.startswith("gc:"))(compatibility_action_p1_08)

    _PREVIOUS_VIRAL_ACTION = viral_upgrade.viral_action_v2
    group_router.callback_query.handlers[:] = [
        handler
        for handler in group_router.callback_query.handlers
        if handler.callback is not viral_upgrade.viral_action_v2
    ]
    group_router.callback_query(F.data.startswith(("v:", "g2:")))(viral_action_p1_08)
    group_router.callback_query(F.data.startswith("p108:private:"))(group_to_private)
    group_router.message(F.new_chat_members)(group_added)

    core_handlers.router.callback_query(F.data == "menu:friends")(friends_entry)
    core_handlers.router.callback_query(F.data == "friends:add")(friends_add)

    _INSTALL_MARKERS.add("group_p1_08")
