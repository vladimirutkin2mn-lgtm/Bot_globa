"""Task 06: compact group entry and context-preserving quick compatibility.

Legacy group commands remain available, but the primary group CJM intentionally exposes
only the two games a new group needs to understand: compatibility and Astro Duel.
Compatibility keeps its selected context even when natal profiles are missing and moves
straight into self-confirmed sun-sign selection instead of an intermediate upsell screen.
"""

from collections.abc import Awaitable, Callable
from html import escape

from aiogram import Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import chat_scope_handlers
from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_handlers, group_p1_08
from app.bot import group_viral_handlers as viral
from app.bot import group_viral_upgrade as viral_upgrade
from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art
from app.domain.natal_chart import NatalChartResult, ZodiacSign
from app.domain.synastry import CompatibilityContext
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService

_INSTALL_MARKERS: set[str] = set()
_PREVIOUS_COMPATIBILITY_RENDER: Callable[..., Awaitable[None]] | None = None

GROUP_ENTRY_TEXT = (
    "✨ <b>Быстро поиграть вместе</b>\n\n"
    "Выберите игру. Участники подтверждают себя сами кнопками, а если натальной карты нет — "
    "достаточно выбрать свой знак.\n\n"
    "Numa не читает обычную переписку группы и не требует прав администратора."
)

_QUICK_METRIC_LABELS: dict[CompatibilityContext, tuple[str, str, str]] = {
    CompatibilityContext.LOVE: ("🔥 Притяжение", "💬 Общение", "🏠 В долгую"),
    CompatibilityContext.FRIENDSHIP: ("🤝 Лёгкость вместе", "💬 Общение", "🧭 Надёжность"),
    CompatibilityContext.WORK: ("⚙️ Рабочий ритм", "💬 Коммуникация", "🎯 Стабильность"),
    CompatibilityContext.TRAVEL: ("🧭 Совпадение ритма", "💬 Договорённости", "🧳 В пути"),
}


def compact_group_menu() -> InlineKeyboardMarkup:
    """Keep the first group decision to the two core multiplayer games."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💞 Совместимость", callback_data="gcu:open")],
            [InlineKeyboardButton(text="⚔️ Астро-дуэль", callback_data="v:o:d")],
        ]
    )


def _context_code(context: CompatibilityContext) -> str:
    return compatibility._CONTEXT_CODES[context]


def _context_from_code(code: str) -> CompatibilityContext:
    try:
        return compatibility._CONTEXT_BY_CODE[code]
    except KeyError as exc:
        raise ValueError("unknown compatibility context") from exc


def _context_sign_keyboard(
    context: CompatibilityContext,
    first_id: int,
    second_id: int,
    signs: tuple[str, str],
    slot: int,
) -> InlineKeyboardMarkup:
    pair = viral_upgrade._pair_payload(first_id, second_id)
    state = ".".join(signs)
    context_code = _context_code(context)
    buttons = [
        InlineKeyboardButton(
            text=compatibility._ZODIAC_RU[sign],
            callback_data=(
                f"g3:z:{context_code}:{pair}:{state}:{slot}:{viral_upgrade._SIGN_CODE[sign]}"
            ),
        )
        for sign in ZodiacSign
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[buttons[index : index + 3] for index in range(0, 12, 3)]
    )


def _precision_keyboard(
    username: str | None,
    *,
    context: CompatibilityContext,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if username:
        clean_username = username.removeprefix("@")
        for name in (first_name, second_name):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🪐 {name}: сделать точнее",
                        url=f"https://t.me/{clean_username}?start=astro",
                    )
                ]
            )
    pair = viral_upgrade._pair_payload(first_id, second_id)
    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Посчитать точнее",
                callback_data=f"g3:r:{_context_code(context)}:{pair}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quick_context_text(
    *,
    context: CompatibilityContext,
    first_name: str,
    second_name: str,
    first_sign: ZodiacSign,
    second_sign: ZodiacSign,
    result: viral_upgrade.QuickCompatibility,
    card_name: str,
    card_theme: str,
) -> str:
    """Render the quick result in the exact context chosen before sign intake."""

    first_metric, second_metric, third_metric = _QUICK_METRIC_LABELS[context]
    return (
        f"💞 <b>{escape(first_name)} × {escape(second_name)}</b>\n"
        f"{compatibility._CONTEXT_LABELS[context]} · "
        f"{compatibility._CONTEXT_SCORE_LABELS[context]} <b>{result.overall}%</b>\n\n"
        f"☀️ {compatibility._ZODIAC_RU[first_sign]} × "
        f"{compatibility._ZODIAC_RU[second_sign]}\n"
        f"{first_metric} — <b>{result.attraction}%</b>\n"
        f"{second_metric} — <b>{result.communication}%</b>\n"
        f"{third_metric} — <b>{result.long_term}%</b>\n\n"
        f"🃏 Карта пары — {escape(card_name)}: {escape(card_theme)}.\n\n"
        "<em>Быстрый режим по солнечным знакам. Выбранный ракурс сохранён; "
        "натальная синастрия даст более точный результат.</em>"
    )


async def _start_context_signs(
    message: Message,
    bot: Bot,
    *,
    context: CompatibilityContext,
    first_id: int,
    second_id: int,
    first_chart: NatalChartResult | None,
    second_chart: NatalChartResult | None,
) -> None:
    signs = (viral_upgrade._sign_token(first_chart), viral_upgrade._sign_token(second_chart))
    slot = 0 if signs[0] == "x" else 1 if signs[1] == "x" else None
    if slot is None:
        raise ValueError("quick sign intake requires a missing natal chart")
    expected_id = first_id if slot == 0 else second_id
    expected_name = await compatibility._member_name(bot, message, expected_id)
    await message.edit_text(
        f"☀️ <b>{escape(expected_name)}, выбери свой знак</b>\n\n"
        f"Ракурс уже сохранён: {compatibility._CONTEXT_LABELS[context]}.",
        reply_markup=_context_sign_keyboard(context, first_id, second_id, signs, slot),
    )


async def _render_compatibility_cjm(
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
    """Go straight to sign intake when either natal chart is unavailable."""

    first_chart = await compatibility._chart_for(first_id, onboarding, birth_profile_service)
    second_chart = await compatibility._chart_for(second_id, onboarding, birth_profile_service)
    if first_chart is None or second_chart is None:
        await _start_context_signs(
            message,
            bot,
            context=context,
            first_id=first_id,
            second_id=second_id,
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


async def _render_quick_context_result(
    message: Message,
    bot: Bot,
    *,
    context: CompatibilityContext,
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign,
    second_sign: ZodiacSign,
) -> None:
    first_name, second_name = await compatibility._pair_names(bot, message, first_id, second_id)
    result = viral_upgrade.quick_compatibility_for_signs(first_sign, second_sign)
    card = viral._stable_card(
        "group-context-compatibility-v3",
        message.chat.id,
        message.date.date(),
        first_id,
        second_id,
        context.value,
    )
    text = quick_context_text(
        context=context,
        first_name=first_name,
        second_name=second_name,
        first_sign=first_sign,
        second_sign=second_sign,
        result=result,
        card_name=card.name_ru,
        card_theme=card.upright_theme,
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=_precision_keyboard(
            await viral._bot_username(bot),
            context=context,
            first_id=first_id,
            second_id=second_id,
            first_name=first_name,
            second_name=second_name,
        ),
    )


async def _save_context_sign(
    callback: CallbackQuery,
    message: Message,
    bot: Bot,
    *,
    context: CompatibilityContext,
    first_id: int,
    second_id: int,
    signs: tuple[str, str],
    slot: int,
    code: str,
) -> None:
    expected = first_id if slot == 0 else second_id
    if callback.from_user.id != expected or code not in viral_upgrade._SIGN_BY_CODE:
        await callback.answer("Эту кнопку должен нажать выбранный участник.")
        return
    values = list(signs)
    values[slot] = code
    if "x" in values:
        next_slot = values.index("x")
        next_id = first_id if next_slot == 0 else second_id
        next_name = await compatibility._member_name(bot, message, next_id)
        await callback.answer("Знак выбран ✨")
        await message.edit_text(
            f"☀️ Теперь <b>{escape(next_name)}</b> выбирает свой знак.\n\n"
            f"Ракурс: {compatibility._CONTEXT_LABELS[context]}.",
            reply_markup=_context_sign_keyboard(
                context,
                first_id,
                second_id,
                (values[0], values[1]),
                next_slot,
            ),
        )
        return
    await callback.answer("Готово ✨")
    await message.edit_text(
        f"✨ Знаки выбраны. Считаю: {compatibility._CONTEXT_LABELS[context]}…",
        reply_markup=None,
    )
    await _render_quick_context_result(
        message,
        bot,
        context=context,
        first_id=first_id,
        second_id=second_id,
        first_sign=viral_upgrade._SIGN_BY_CODE[values[0]],
        second_sign=viral_upgrade._SIGN_BY_CODE[values[1]],
    )


async def group_cjm_action(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
) -> None:
    message = callback.message
    data = callback.data or ""
    if not isinstance(message, Message):
        await callback.answer()
        return
    try:
        if data.startswith("g3:z:"):
            _, _, raw_context, pair, raw_signs, raw_slot, code = data.split(":", 6)
            first_id, second_id = viral_upgrade._decode_pair(pair)
            await _save_context_sign(
                callback,
                message,
                bot,
                context=_context_from_code(raw_context),
                first_id=first_id,
                second_id=second_id,
                signs=viral_upgrade._decode_signs(raw_signs),
                slot=int(raw_slot),
                code=code,
            )
            return
        if data.startswith("g3:r:"):
            _, _, raw_context, pair = data.split(":", 3)
            context = _context_from_code(raw_context)
            first_id, second_id = viral_upgrade._decode_pair(pair)
            if callback.from_user.id not in {first_id, second_id}:
                await callback.answer("Проверить точный результат могут только участники пары.")
                return
            first_chart = await compatibility._chart_for(
                first_id, onboarding, birth_profile_service
            )
            second_chart = await compatibility._chart_for(
                second_id, onboarding, birth_profile_service
            )
            if first_chart is None or second_chart is None:
                await callback.answer("Натальная карта пока не готова.")
                return
            await callback.answer("Считаю точнее ✨")
            assert _PREVIOUS_COMPATIBILITY_RENDER is not None
            await _PREVIOUS_COMPATIBILITY_RENDER(
                message,
                bot,
                onboarding,
                birth_profile_service,
                context=context,
                inviter_id=first_id,
                first_id=first_id,
                second_id=second_id,
            )
            return
    except (KeyError, TypeError, ValueError):
        await callback.answer("Не получилось продолжить совместимость.")
        return
    await callback.answer()


async def group_added_cjm(message: Message, bot: Bot) -> None:
    """Use the same compact group entry when Numa is added to a chat."""

    members = message.new_chat_members or []
    if not members:
        return
    me = await bot.get_me()
    if all(member.id != me.id for member in members):
        return
    await message.answer(GROUP_ENTRY_TEXT, reply_markup=compact_group_menu())


def install_group_cjm_v3() -> None:
    """Install the final Task 06 group surface after all legacy additive mechanics."""

    global _PREVIOUS_COMPATIBILITY_RENDER

    if "group_cjm_v3" in _INSTALL_MARKERS:
        return

    _PREVIOUS_COMPATIBILITY_RENDER = compatibility._render_compatibility
    compatibility._render_compatibility = _render_compatibility_cjm
    vars(group_handlers)["_party_menu_keyboard"] = compact_group_menu
    vars(chat_scope_handlers)["GROUP_ENTRY_TEXT"] = GROUP_ENTRY_TEXT

    router = group_handlers.router
    router.message.handlers[:] = [
        handler for handler in router.message.handlers if handler.callback is not group_p1_08.group_added
    ]
    router.message(F.new_chat_members)(group_added_cjm)
    router.callback_query(F.data.startswith("g3:"))(group_cjm_action)

    _INSTALL_MARKERS.add("group_cjm_v3")
