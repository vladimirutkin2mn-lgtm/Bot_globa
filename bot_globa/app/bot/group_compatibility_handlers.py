"""Interactive, consented natal compatibility for Telegram group chats."""

from html import escape

from aiogram import Bot, F
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_handlers
from app.domain.natal_chart import NatalBody, NatalChartResult, NatalTimePrecision, ZodiacSign
from app.domain.synastry import CompatibilityContext, SynastryResult, calculate_synastry
from app.services.birth_profile import BirthProfileConsentRequiredError, BirthProfileService
from app.services.natal_chart import AstronomyEngineNatalChartCalculator
from app.services.onboarding import OnboardingService

_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_INSTALL_MARKERS: set[str] = set()
_CALCULATOR = AstronomyEngineNatalChartCalculator()

_CONTEXT_LABELS: dict[CompatibilityContext, str] = {
    CompatibilityContext.LOVE: "❤️ Любовь",
    CompatibilityContext.FRIENDSHIP: "🤝 Дружба",
    CompatibilityContext.WORK: "💼 Работа",
    CompatibilityContext.TRAVEL: "✈️ Поездка",
}
_CONTEXT_CODES: dict[CompatibilityContext, str] = {
    CompatibilityContext.LOVE: "l",
    CompatibilityContext.FRIENDSHIP: "f",
    CompatibilityContext.WORK: "w",
    CompatibilityContext.TRAVEL: "t",
}
_CONTEXT_BY_CODE = {code: context for context, code in _CONTEXT_CODES.items()}
_CONTEXT_SCORE_LABELS: dict[CompatibilityContext, str] = {
    CompatibilityContext.LOVE: "Любовный потенциал",
    CompatibilityContext.FRIENDSHIP: "Дружеская совместимость",
    CompatibilityContext.WORK: "Рабочая совместимость",
    CompatibilityContext.TRAVEL: "Совместимость в поездке",
}
_ZODIAC_RU: dict[ZodiacSign, str] = {
    ZodiacSign.ARIES: "Овен",
    ZodiacSign.TAURUS: "Телец",
    ZodiacSign.GEMINI: "Близнецы",
    ZodiacSign.CANCER: "Рак",
    ZodiacSign.LEO: "Лев",
    ZodiacSign.VIRGO: "Дева",
    ZodiacSign.LIBRA: "Весы",
    ZodiacSign.SCORPIO: "Скорпион",
    ZodiacSign.SAGITTARIUS: "Стрелец",
    ZodiacSign.CAPRICORN: "Козерог",
    ZodiacSign.AQUARIUS: "Водолей",
    ZodiacSign.PISCES: "Рыбы",
}


class GroupCompatibilityStates(StatesGroup):
    waiting_for_second = State()


def _entry_keyboard(inviter_id: int, selected_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💞 Я + этот человек",
                    callback_data=f"gc:s:{inviter_id}:{selected_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Этот человек + другой",
                    callback_data=f"gc:o:{inviter_id}:{selected_id}",
                )
            ],
        ]
    )


def _consent_keyboard(
    inviter_id: int,
    first_id: int,
    second_id: int,
    *,
    step: int,
) -> InlineKeyboardMarkup:
    action = "a" if step == 1 else "b"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Да, посмотрим",
                    callback_data=(f"gc:{action}:{inviter_id}:{first_id}:{second_id}"),
                )
            ]
        ]
    )


def _context_keyboard(inviter_id: int, first_id: int, second_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=label,
            callback_data=(f"gc:c:{_CONTEXT_CODES[context]}:{inviter_id}:{first_id}:{second_id}"),
        )
        for context, label in _CONTEXT_LABELS.items()
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[[buttons[0], buttons[1]], [buttons[2], buttons[3]]]
    )


def _result_keyboard(
    bot_username: str | None,
    inviter_id: int,
    first_id: int,
    second_id: int,
) -> InlineKeyboardMarkup:
    rows = [list(row) for row in _context_keyboard(inviter_id, first_id, second_id).inline_keyboard]
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💞 Разобрать отношения лично",
                    url=group_handlers.private_deep_link(bot_username, "love"),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _profile_keyboard(
    bot_username: str | None,
    missing: list[tuple[int, str]],
    *,
    context: CompatibilityContext,
    inviter_id: int,
    first_id: int,
    second_id: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        for _, name in missing:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🪐 {name}: заполнить астропрофиль",
                        url=f"https://t.me/{bot_username.removeprefix('@')}?start=astro",
                    )
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Проверить снова",
                callback_data=(
                    f"gc:r:{_CONTEXT_CODES[context]}:{inviter_id}:{first_id}:{second_id}"
                ),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def compatibility_entry(message: Message) -> None:
    author = message.from_user
    replied = message.reply_to_message
    selected = replied.from_user if replied is not None else None
    if author is None:
        return
    if selected is None or selected.is_bot or selected.id == author.id:
        await message.answer(
            "💞 Ответьте /compatibility на сообщение человека, "
            "которого хотите выбрать.\n\n"
            "Дальше можно сравнить его с собой или выбрать "
            "второго участника."
        )
        return
    await message.answer(
        (f"💞 Первый участник — {escape(selected.full_name)}.\n\nС кем сравниваем?"),
        reply_markup=_entry_keyboard(author.id, selected.id),
    )


async def compatibility_second(message: Message, bot: Bot, state: FSMContext) -> None:
    author = message.from_user
    replied = message.reply_to_message
    second = replied.from_user if replied is not None else None
    data = await state.get_data()
    first_id = data.get("compatibility_first_id")
    first_name = data.get("compatibility_first_name")
    if author is None or not isinstance(first_id, int) or not isinstance(first_name, str):
        await state.clear()
        return
    if second is None or second.is_bot or second.id in {author.id, first_id}:
        await message.answer("👥 Ответьте /with на сообщение другого участника чата.")
        return
    await state.clear()
    await message.answer(
        (
            f"💞 Пара выбрана: {escape(first_name)} × "
            f"{escape(second.full_name)}.\n\n"
            f"{escape(first_name)}, сначала нужно твоё согласие на "
            "использование астропрофиля для результата в группе."
        ),
        reply_markup=_consent_keyboard(author.id, first_id, second.id, step=1),
    )


async def compatibility_action(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
) -> None:
    message = callback.message
    data = callback.data
    if not isinstance(message, Message) or message.chat.type not in _GROUP_TYPES or data is None:
        await callback.answer()
        return
    parts = data.split(":")
    if len(parts) < 2 or parts[0] != "gc":
        await callback.answer()
        return
    action = parts[1]

    try:
        if action in {"s", "o"} and len(parts) == 4:
            inviter_id, selected_id = int(parts[2]), int(parts[3])
            await _handle_pair_choice(
                callback,
                message,
                bot,
                state,
                inviter_id=inviter_id,
                selected_id=selected_id,
                choose_other=action == "o",
            )
            return
        if action in {"a", "b"} and len(parts) == 5:
            inviter_id, first_id, second_id = map(int, parts[2:5])
            await _handle_consent(
                callback,
                message,
                bot,
                inviter_id=inviter_id,
                first_id=first_id,
                second_id=second_id,
                step=1 if action == "a" else 2,
            )
            return
        if action == "c" and len(parts) == 6:
            context = _CONTEXT_BY_CODE[parts[2]]
            inviter_id, first_id, second_id = map(int, parts[3:6])
            if callback.from_user.id != inviter_id:
                await callback.answer("Ракурс выбирает тот, кто запустил сравнение.")
                return
            await callback.answer("Смотрю карты ✨")
            await _render_compatibility(
                message,
                bot,
                onboarding,
                birth_profile_service,
                context=context,
                inviter_id=inviter_id,
                first_id=first_id,
                second_id=second_id,
            )
            return
        if action == "r" and len(parts) == 6:
            context = _CONTEXT_BY_CODE[parts[2]]
            inviter_id, first_id, second_id = map(int, parts[3:6])
            if callback.from_user.id not in {inviter_id, first_id, second_id}:
                await callback.answer("Проверить готовность могут только участники сравнения.")
                return
            await callback.answer("Проверяю профили ✨")
            await _render_compatibility(
                message,
                bot,
                onboarding,
                birth_profile_service,
                context=context,
                inviter_id=inviter_id,
                first_id=first_id,
                second_id=second_id,
            )
            return
    except (KeyError, TypeError, ValueError):
        await callback.answer("Не получилось открыть совместимость.")
        return
    await callback.answer()


async def _handle_pair_choice(
    callback: CallbackQuery,
    message: Message,
    bot: Bot,
    state: FSMContext,
    *,
    inviter_id: int,
    selected_id: int,
    choose_other: bool,
) -> None:
    if callback.from_user.id != inviter_id:
        await callback.answer("Пару выбирает тот, кто запустил сценарий.")
        return
    selected_name = await _member_name(bot, message, selected_id)
    if choose_other:
        await state.set_state(GroupCompatibilityStates.waiting_for_second)
        await state.set_data(
            {
                "compatibility_first_id": selected_id,
                "compatibility_first_name": selected_name,
            }
        )
        await callback.answer()
        await message.edit_text(
            f"👥 Первый — {escape(selected_name)}.\n\n"
            "Теперь ответьте /with на сообщение второго "
            "человека."
        )
        return
    inviter_name = await _member_name(bot, message, inviter_id)
    await callback.answer()
    await message.edit_text(
        (
            f"💞 {escape(inviter_name)} × {escape(selected_name)}\n\n"
            f"{escape(selected_name)}, участвуешь? После согласия Numa "
            "использует ваши астропрофили только для этого "
            "результата в группе."
        ),
        reply_markup=_consent_keyboard(inviter_id, inviter_id, selected_id, step=2),
    )


async def _handle_consent(
    callback: CallbackQuery,
    message: Message,
    bot: Bot,
    *,
    inviter_id: int,
    first_id: int,
    second_id: int,
    step: int,
) -> None:
    expected_user = first_id if step == 1 else second_id
    if callback.from_user.id != expected_user:
        await callback.answer("Эту кнопку должен нажать выбранный участник.")
        return
    first_name, second_name = await _pair_names(bot, message, first_id, second_id)
    await callback.answer("Согласие принято ✨")
    if step == 1:
        await message.edit_text(
            f"💞 {escape(first_name)} × {escape(second_name)}\n\n"
            f"{escape(second_name)}, теперь твоё согласие.",
            reply_markup=_consent_keyboard(inviter_id, first_id, second_id, step=2),
        )
        return
    await message.edit_text(
        (f"💞 {escape(first_name)} × {escape(second_name)}\n\nЧто именно смотрим?"),
        reply_markup=_context_keyboard(inviter_id, first_id, second_id),
    )


async def _render_compatibility(
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
    first_name, second_name = await _pair_names(bot, message, first_id, second_id)
    first_chart = await _chart_for(first_id, onboarding, birth_profile_service)
    second_chart = await _chart_for(second_id, onboarding, birth_profile_service)
    missing: list[tuple[int, str]] = []
    if first_chart is None:
        missing.append((first_id, first_name))
    if second_chart is None:
        missing.append((second_id, second_name))
    username = (await bot.get_me()).username
    if missing:
        names = ", ".join(escape(name) for _, name in missing)
        await message.edit_text(
            "🪐 Для настоящей астросовместимости нужны "
            "натальные данные обоих.\n\n"
            f"Нужно заполнить астропрофиль: {names}.\n"
            "После этого вернитесь сюда и нажмите "
            "«Проверить снова».",
            reply_markup=_profile_keyboard(
                username,
                missing,
                context=context,
                inviter_id=inviter_id,
                first_id=first_id,
                second_id=second_id,
            ),
        )
        return
    result = calculate_synastry(first_chart, second_chart, context)
    text = _render_result(first_name, second_name, first_chart, second_chart, result)
    await message.edit_text(
        text,
        reply_markup=_result_keyboard(username, inviter_id, first_id, second_id),
    )


async def _chart_for(
    telegram_user_id: int,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
) -> NatalChartResult | None:
    user = await onboarding.current_user(telegram_user_id)
    if user is None:
        return None
    try:
        return await birth_profile_service.use_profile(user.id, _CALCULATOR.calculate)
    except (BirthProfileConsentRequiredError, LookupError):
        return None


def _render_result(
    first_name: str,
    second_name: str,
    first_chart: NatalChartResult,
    second_chart: NatalChartResult,
    result: SynastryResult,
) -> str:
    first_sun = _sign(first_chart, NatalBody.SUN)
    second_sun = _sign(second_chart, NatalBody.SUN)
    first_venus = _sign(first_chart, NatalBody.VENUS)
    second_venus = _sign(second_chart, NatalBody.VENUS)
    first_mars = _sign(first_chart, NatalBody.MARS)
    second_mars = _sign(second_chart, NatalBody.MARS)
    precision = ""
    if (
        first_chart.time_precision is NatalTimePrecision.DATE_ONLY
        or second_chart.time_precision is NatalTimePrecision.DATE_ONLY
    ):
        precision = (
            "\n\n<em>У кого-то не указано точное время рождения — "
            "Луна может быть менее точной.</em>"
        )
    return (
        f"💞 <b>{escape(first_name)} × {escape(second_name)}</b>\n"
        f"{_CONTEXT_LABELS[result.context]} · {_CONTEXT_SCORE_LABELS[result.context]} "
        f"<b>{result.overall}%</b>\n\n"
        f"☀️ Солнце: {first_sun} × {second_sun}\n"
        f"💗 Венера: {first_venus} × {second_venus}\n"
        f"🔥 Марс: {first_mars} × {second_mars}\n\n"
        f"❤️ Притяжение — <b>{result.scores.attraction}%</b>\n"
        f"💬 Общение — <b>{result.scores.communication}%</b>\n"
        f"🌙 Эмоциональный ритм — <b>{result.scores.emotional}%</b>\n"
        f"🏠 В долгую — <b>{result.scores.stability}%</b>\n\n"
        f"✨ Сильнее всего: {result.strongest}.\n"
        f"⚡ Точка напряжения: {result.weakest}.\n\n"
        f"<b>Вердикт Numa:</b> {result.verdict}"
        f"{precision}\n\n"
        "<em>Астрологический игровой разбор, а не оценка реальных "
        "чувств или отношений.</em>"
    )


def _sign(chart: NatalChartResult, body: NatalBody) -> str:
    position = next(position for position in chart.planets if position.body is body)
    return _ZODIAC_RU[position.sign]


async def _member_name(bot: Bot, message: Message, user_id: int) -> str:
    try:
        member = await bot.get_chat_member(message.chat.id, user_id)
    except TelegramAPIError:
        return "участник"
    return member.user.full_name


async def _pair_names(bot: Bot, message: Message, first_id: int, second_id: int) -> tuple[str, str]:
    return await _member_name(bot, message, first_id), await _member_name(bot, message, second_id)


def install_group_compatibility_mechanics() -> None:
    """Replace the old random pair vibe with the interactive natal flow once."""

    if "group_compatibility" in _INSTALL_MARKERS:
        return
    router = group_handlers.router
    router.message.handlers[:] = [
        handler
        for handler in router.message.handlers
        if handler.callback is not group_handlers.compatibility
    ]
    router.message(_GROUP_CHAT, Command("compatibility"))(compatibility_entry)
    router.message(
        _GROUP_CHAT,
        GroupCompatibilityStates.waiting_for_second,
        Command("with"),
    )(compatibility_second)
    router.callback_query(F.data.startswith("gc:"))(compatibility_action)
    group_handlers.GROUP_HELP = group_handlers.GROUP_HELP.replace(
        "💞 /compatibility — вайб двух участников на сегодня",
        "💞 /compatibility — совместимость по натальной карте",
    ).replace(
        "• /compatibility — ответьте командой на сообщение человека.",
        ("• /compatibility — выберите одного человека reply-командой; затем себя или второго."),
    )
    _INSTALL_MARKERS.add("group_compatibility")
