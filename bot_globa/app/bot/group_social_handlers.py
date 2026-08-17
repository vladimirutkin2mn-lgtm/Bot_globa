"""Extra privacy-safe social mechanics for Telegram group chats."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html import escape

from aiogram import Bot, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_handlers
from app.bot.group_handlers import duel_for_day, private_deep_link
from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art
from app.domain.tarot import RWS_78_V1, TarotCard

_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_INSTALL_MARKERS: set[str] = set()

ROLE_TITLES = (
    "Провокатор",
    "Миротворец",
    "Авантюрист",
    "Стратег",
    "Хранитель здравого смысла",
    "Главный по спонтанности",
    "Дипломат",
    "Генератор идей",
    "Свидетель хаоса",
    "Человек «а давайте»",
)
AFTER_MIDNIGHT_PROMPTS = (
    "Кто-то предложит план, который утром будет звучать гораздо смелее, чем сейчас.",
    "Самая запоминающаяся история вечера начнётся со слов: «это займёт пять минут».",
    "Сегодня случайная фраза может стать локальным мемом этого чата.",
    "Самый правильный план после полуночи — тот, которого вообще не было в плане.",
    "Кто-то скажет «последний раз — и домой». Вселенная услышит только первую половину.",
)
SECRET_QUESTIONS = (
    "Один человек в этом чате сегодня особенно часто думает о переменах 👀",
    "Кому-то здесь хочется сделать шаг, о котором он пока говорит только мысленно.",
    "У кого-то здесь есть вопрос, который проще задать карте, чем друзьям.",
    "Кто-то здесь уже почти решился на маленькую авантюру.",
)
PREDICTIONS = (
    "До полуночи кто-то предложит неожиданный план.",
    "Сегодня в чате появится сообщение, после которого планы слегка поменяются.",
    "Кто-то вспомнит историю, которую все уже знают — и всё равно обсудят снова.",
    "До конца дня один человек скажет «а почему бы и нет?» и запустит движение.",
    "Сегодня маленький спор закончится лучше, чем начался.",
)
MIRROR_THEMES: dict[str, tuple[str, str]] = {
    "love": ("💞 Отношения", "как вы держитесь друг за друга"),
    "money": ("💸 Деньги", "как чат относится к планам, риску и тратам"),
    "adventure": ("🧭 Приключения", "как вы входите в новое и неожиданное"),
    "chaos": ("🌪 Хаос", "что происходит, когда план перестаёт быть планом"),
}
VERSUS_PROMPTS = (
    "Кто сегодня скорее рискнёт?",
    "Кто будет тормозить сомнительную идею?",
    "Кто первым скажет: «я же говорил»?",
)
WEEKDAY_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

GROUP_SOCIAL_HELP = (
    "🔮 Numa в этом чате\n\n"
    "Команды:\n\n"
    "🔮 /card — карта дня для всего чата\n"
    "💞 /compatibility — вайб двух участников на сегодня\n"
    "🎉 /party — игры для компании\n"
    "🃏 /event — расклад на событие\n"
    "🎭 /chat — архетип этого чата\n"
    "✨ /grouphelp — показать эту подсказку\n\n"
    "Как использовать:\n"
    "• /compatibility — ответьте командой на сообщение человека.\n"
    "• /party — выберите игру кнопкой.\n"
    "• /event — выберите вечер, поездку или событие кнопкой.\n\n"
    "Ещё механики:\n"
    "🔮 /forecast — что ждёт чат сегодня\n"
    "⚔️ /duel — дуэль с участником, ответом на его сообщение\n"
    "🔥 /versus — кто из вас сегодня скорее…\n"
    "👑 /roles — роли дня\n"
    "🃏 /cards — карта каждому добровольцу\n"
    "🔁 /karma — день групповой кармы\n"
    "🏆 /week — итоги недели чата\n\n"
    "Все групповые расклады — игровой формат. Личные вопросы лучше задавать Numa один на один."
)


@dataclass(frozen=True, slots=True)
class RoleDay:
    roles: tuple[str, str, str]
    cards: tuple[TarotCard, TarotCard, TarotCard]


@dataclass(frozen=True, slots=True)
class VersusResult:
    winners: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class WeekSummary:
    main_card: TarotCard
    chaos_weekday: int


def _digest(*parts: object) -> bytes:
    return hashlib.sha256(":".join(str(part) for part in parts).encode()).digest()


def _stable_card(namespace: str, *parts: object) -> TarotCard:
    seed = _digest(namespace, *parts)
    return RWS_78_V1.cards[int.from_bytes(seed[:4], "big") % len(RWS_78_V1.cards)]


def _stable_cards(namespace: str, count: int, *parts: object) -> tuple[TarotCard, ...]:
    seed = _digest(namespace, *parts)
    ranked = sorted(RWS_78_V1.cards, key=lambda card: _digest(seed.hex(), card.code))
    return tuple(ranked[:count])


def role_day_for_chat(chat_id: int, for_date: date) -> RoleDay:
    seed = _digest("group-role-day-v1", chat_id, for_date.isoformat())
    roles = sorted(ROLE_TITLES, key=lambda role: _digest(seed.hex(), role))[:3]
    cards = _stable_cards("group-role-cards-v1", 3, chat_id, for_date.isoformat())
    return RoleDay((roles[0], roles[1], roles[2]), (cards[0], cards[1], cards[2]))


def forecast_for_chat(chat_id: int, for_date: date) -> tuple[TarotCard, TarotCard, TarotCard]:
    cards = _stable_cards("group-forecast-v1", 3, chat_id, for_date.isoformat())
    return cards[0], cards[1], cards[2]


def versus_for_day(first_user_id: int, second_user_id: int, for_date: date) -> VersusResult:
    if first_user_id == second_user_id:
        raise ValueError("versus requires two users")
    left, right = sorted((first_user_id, second_user_id))
    seed = _digest("group-versus-v1", left, right, for_date.isoformat())
    pair = (left, right)
    return VersusResult((pair[seed[0] & 1], pair[seed[1] & 1], pair[seed[2] & 1]))


def individual_card_for_day(chat_id: int, user_id: int, for_date: date) -> TarotCard:
    return _stable_card("group-person-card-v1", chat_id, user_id, for_date.isoformat())


def mirror_card_for_day(chat_id: int, theme: str, for_date: date) -> TarotCard:
    if theme not in MIRROR_THEMES:
        raise ValueError("unsupported mirror theme")
    return _stable_card("group-mirror-v1", chat_id, theme, for_date.isoformat())


def karma_for_day(chat_id: int, for_date: date) -> tuple[int, TarotCard]:
    return (for_date.toordinal() - 1) % 7 + 1, _stable_card(
        "group-karma-v1", chat_id, for_date.isoformat()
    )


def week_summary_for_day(chat_id: int, for_date: date) -> WeekSummary:
    week_start = for_date - timedelta(days=for_date.weekday())
    cards = [
        _stable_card("group-karma-v1", chat_id, (week_start + timedelta(days=i)).isoformat())
        for i in range(7)
    ]
    seed = _digest("group-week-v1", chat_id, week_start.isoformat())
    return WeekSummary(cards[seed[0] % 7], seed[1] % 7)


def _pick_text(items: tuple[str, ...], namespace: str, chat_id: int, for_date: date) -> str:
    seed = _digest(namespace, chat_id, for_date.isoformat())
    return items[seed[0] % len(items)]


def _social_party_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Кто сегодня…", callback_data="group:party:who:0"),
                InlineKeyboardButton(text="👑 Роль дня", callback_data="social:party:roles"),
            ],
            [
                InlineKeyboardButton(
                    text="🌙 Прогноз на вечер", callback_data="social:party:evening"
                ),
                InlineKeyboardButton(
                    text="🥂 После полуночи", callback_data="social:party:midnight"
                ),
            ],
            [
                InlineKeyboardButton(text="🤫 Тайный вопрос", callback_data="social:party:secret"),
                InlineKeyboardButton(text="🪞 Карта о вас", callback_data="social:party:mirror"),
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Предсказание дня", callback_data="social:party:prediction"
                ),
                InlineKeyboardButton(text="🃏 Карта каждому", callback_data="social:party:cards"),
            ],
        ]
    )


def _party_back(
    username: str | None, label: str = "🔮 Что сегодня про меня?"
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if username:
        rows.append(
            [InlineKeyboardButton(text=label, url=private_deep_link(username, "tarot"))]
        )
    rows.append([InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mirror_keyboard() -> InlineKeyboardMarkup:
    items = list(MIRROR_THEMES.items())
    rows = [
        [
            InlineKeyboardButton(text=label, callback_data=f"social:mirror:{code}")
            for code, (label, _) in items[:2]
        ],
        [
            InlineKeyboardButton(text=label, callback_data=f"social:mirror:{code}")
            for code, (label, _) in items[2:]
        ],
        [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cards_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🃏 Получить свою карту", callback_data="social:cards:draw")],
            [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
        ]
    )


async def _bot_username(bot: Bot) -> str | None:
    return (await bot.get_me()).username


def _group_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    if isinstance(message, Message) and message.chat.type in _GROUP_TYPES:
        return message
    return None


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _reply_pair(message: Message) -> tuple[int, str, int, str] | None:
    author = message.from_user
    replied = message.reply_to_message
    partner = replied.from_user if replied is not None else None
    if author is None or partner is None or partner.is_bot or partner.id == author.id:
        return None
    return author.id, escape(author.full_name), partner.id, escape(partner.full_name)


async def _send_roles(message: Message, bot: Bot, for_date: date) -> None:
    result = role_day_for_chat(message.chat.id, for_date)
    lines = [
        f"{i}. {role} — {card.name_ru}: {card.upright_theme}."
        for i, (role, card) in enumerate(zip(result.roles, result.cards, strict=True), 1)
    ]
    text = "👑 Роли дня\n\n" + "\n".join(lines) + "\n\nРаспределяйте роли сами 👀"
    await send_art(
        bot,
        message.chat.id,
        card_art(result.cards[0].code),
        text,
        reply_markup=_party_back(await _bot_username(bot), "🔮 Какая роль моя?"),
    )


async def group_forecast(message: Message, bot: Bot) -> None:
    plot, surprise, advice = forecast_for_chat(message.chat.id, message.date.date())
    text = (
        "🔮 Что ждёт этот чат сегодня\n\n"
        f"Главный сюжет — {plot.name_ru}: {plot.upright_theme}.\n"
        f"Неожиданность — {surprise.name_ru}: {surprise.upright_theme}.\n"
        f"Совет — {advice.name_ru}: {advice.upright_theme}."
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(plot.code),
        text,
        reply_markup=_party_back(await _bot_username(bot), "🔮 А что ждёт лично меня?"),
    )


async def group_roles(message: Message, bot: Bot) -> None:
    await _send_roles(message, bot, message.date.date())


async def group_cards(message: Message) -> None:
    await message.answer(
        "🃏 Карта для каждого\n\nНажимайте по очереди — каждому своя карта на сегодня.",
        reply_markup=_cards_keyboard(),
    )


async def group_duel(message: Message, bot: Bot) -> None:
    pair = _reply_pair(message)
    if pair is None:
        await message.answer("⚔️ Ответьте /duel на сообщение человека, с которым хотите дуэль.")
        return
    first_id, first_name, second_id, second_name = pair
    result = duel_for_day(first_id, second_id, message.date.date())
    username = await _bot_username(bot)
    keyboard = None
    if username:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💞 Полный разбор динамики",
                        url=private_deep_link(username, "love"),
                    )
                ]
            ]
        )
    text = (
        f"⚔️ Дуэль дня: {first_name} × {second_name}\n\n"
        f"{first_name} — {result.first_card.name_ru}: {result.first_card.upright_theme}.\n\n"
        f"{second_name} — {result.second_card.name_ru}: {result.second_card.upright_theme}.\n\n"
        f"Между вами — {result.dynamic_card.name_ru}: {result.dynamic_card.upright_theme}."
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.dynamic_card.code),
        text,
        reply_markup=keyboard,
    )


async def group_versus(message: Message, bot: Bot) -> None:
    pair = _reply_pair(message)
    if pair is None:
        await message.answer(
            "🔥 Ответьте /versus на сообщение человека, с которым хотите сравнение."
        )
        return
    first_id, first_name, second_id, second_name = pair
    result = versus_for_day(first_id, second_id, message.date.date())
    names = {first_id: first_name, second_id: second_name}
    lines = [
        f"{prompt} — {names[winner]}"
        for prompt, winner in zip(VERSUS_PROMPTS, result.winners, strict=True)
    ]
    left, right = sorted((first_id, second_id))
    card = _stable_card("group-versus-card-v1", left, right, message.date.date())
    text = f"🔥 Кто из вас…\n\n" + "\n".join(lines) + "\n\nСегодняшний вайб, не приговор."
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=_party_back(await _bot_username(bot), "💞 Персональная совместимость"),
    )


async def group_karma(message: Message, bot: Bot) -> None:
    day_index, card = karma_for_day(message.chat.id, message.date.date())
    text = (
        f"🔁 Карма чата · день {day_index}/7\n\n"
        f"Сегодня — {card.name_ru}.\nТема дня: {card.upright_theme}.\n\n"
        "Возвращайтесь завтра. На седьмой день можно собрать характер недели."
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=_party_back(await _bot_username(bot), "🔮 Моя личная неделя"),
    )


async def group_week(message: Message, bot: Bot) -> None:
    result = week_summary_for_day(message.chat.id, message.date.date())
    text = (
        "🏆 Итоги недели чата\n\n"
        f"Главная карта — {result.main_card.name_ru}.\n"
        f"Главный мотив — {result.main_card.upright_theme}.\n"
        f"Самый хаотичный день — {WEEKDAY_RU[result.chaos_weekday]}."
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.main_card.code),
        text,
        reply_markup=_party_back(await _bot_username(bot), "🔮 Мои итоги недели"),
    )


async def social_party_action(callback: CallbackQuery, bot: Bot) -> None:
    message = _group_message(callback)
    data = callback.data
    if message is None or data is None:
        await callback.answer()
        return
    action = data.removeprefix("social:party:")
    await callback.answer()
    today = _today_utc()
    username = await _bot_username(bot)
    if action == "roles":
        await _send_roles(message, bot, today)
        return
    if action == "evening":
        energy, turn, advice = _stable_cards("group-evening-v1", 3, message.chat.id, today)
        text = (
            "🌙 Прогноз на вечер\n\n"
            f"Энергия — {energy.name_ru}: {energy.upright_theme}.\n"
            f"Поворот — {turn.name_ru}: {turn.upright_theme}.\n"
            f"Лучший сценарий — {advice.name_ru}: {advice.upright_theme}."
        )
        await send_art(
            bot,
            message.chat.id,
            card_art(energy.code),
            text,
            reply_markup=_party_back(username, "🌙 Мой прогноз на вечер"),
        )
        return
    if action == "midnight":
        prompt = _pick_text(AFTER_MIDNIGHT_PROMPTS, "group-midnight-v1", message.chat.id, today)
        card = _stable_card("group-midnight-card-v1", message.chat.id, today)
        await send_art(
            bot,
            message.chat.id,
            card_art(card.code),
            "🥂 После полуночи\n\n" + prompt,
            reply_markup=_party_back(username, "🌙 Что принесёт мой вечер?"),
        )
        return
    if action == "secret":
        prompt = _pick_text(SECRET_QUESTIONS, "group-secret-v1", message.chat.id, today)
        card = _stable_card("group-secret-card-v1", message.chat.id, today)
        text = (
            "🤫 Тайный вопрос\n\n"
            + prompt
            + "\n\nИгровая формулировка: Numa не читает обычные сообщения чата."
        )
        await send_art(
            bot,
            message.chat.id,
            card_art(card.code),
            text,
            reply_markup=_party_back(username, "🔮 Задать настоящий вопрос"),
        )
        return
    if action == "mirror":
        await message.answer("🪞 Что карта скажет о вашем чате?", reply_markup=_mirror_keyboard())
        return
    if action == "prediction":
        yesterday = today - timedelta(days=1)
        yesterday_prediction = _pick_text(
            PREDICTIONS, "group-prediction-v1", message.chat.id, yesterday
        )
        prediction = _pick_text(PREDICTIONS, "group-prediction-v1", message.chat.id, today)
        card = _stable_card("group-prediction-card-v1", message.chat.id, today)
        rows = [
            [
                InlineKeyboardButton(text="Сбылось 😳", callback_data="social:prediction:hit"),
                InlineKeyboardButton(text="Мимо", callback_data="social:prediction:miss"),
            ],
            [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
        ]
        if username:
            rows.insert(
                1,
                [
                    InlineKeyboardButton(
                        text="🔮 Мой личный прогноз",
                        url=private_deep_link(username, "tarot"),
                    )
                ],
            )
        await send_art(
            bot,
            message.chat.id,
            card_art(card.code),
            "🎯 Предсказание дня\n\n"
            + "Вчера Numa сказала: "
            + yesterday_prediction
            + "\n\nА сегодня: "
            + prediction
            + "\n\nВчера сбылось? 👀",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return
    if action == "cards":
        await group_cards(message)


async def social_mirror_action(callback: CallbackQuery, bot: Bot) -> None:
    message = _group_message(callback)
    data = callback.data
    if message is None or data is None:
        await callback.answer()
        return
    theme = data.removeprefix("social:mirror:")
    meta = MIRROR_THEMES.get(theme)
    if meta is None:
        await callback.answer("Такой темы здесь нет.")
        return
    await callback.answer()
    label, description = meta
    card = mirror_card_for_day(message.chat.id, theme, _today_utc())
    text = (
        f"🪞 {label}: что карта говорит о вашем чате\n\n"
        f"{card.name_ru}\nСегодня карта описывает {description}: {card.upright_theme}."
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=_party_back(await _bot_username(bot), "🔮 А что карта скажет обо мне?"),
    )


async def social_person_card(callback: CallbackQuery, bot: Bot) -> None:
    message = _group_message(callback)
    if message is None:
        await callback.answer()
        return
    await callback.answer("Карта выбрана ✨")
    card = individual_card_for_day(message.chat.id, callback.from_user.id, _today_utc())
    username = await _bot_username(bot)
    rows: list[list[InlineKeyboardButton]] = []
    if username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔮 Разобрать мою карту",
                    url=private_deep_link(username, "tarot"),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="🃏 Карта следующему", callback_data="social:cards:draw")]
    )
    name = escape(callback.from_user.full_name)
    text = f"🃏 Карта для {name}\n\n{card.name_ru}\nСегодня твой мотив — {card.upright_theme}."
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def social_prediction_feedback(callback: CallbackQuery) -> None:
    if callback.data == "social:prediction:hit":
        await callback.answer("😳 Похоже, вчера Numa попала.")
        return
    if callback.data == "social:prediction:miss":
        await callback.answer("Красивый промах. Завтра будет новое предсказание 😌")
        return
    await callback.answer()


def install_group_social_mechanics() -> None:
    """Patch the existing group menu and register the additive handlers once."""

    if "group_social" in _INSTALL_MARKERS:
        return
    group_handlers._party_menu_keyboard = _social_party_menu_keyboard
    group_handlers.GROUP_HELP = GROUP_SOCIAL_HELP
    router = group_handlers.router
    router.message(_GROUP_CHAT, Command("forecast"))(group_forecast)
    router.message(_GROUP_CHAT, Command("roles"))(group_roles)
    router.message(_GROUP_CHAT, Command("cards"))(group_cards)
    router.message(_GROUP_CHAT, Command("duel"))(group_duel)
    router.message(_GROUP_CHAT, Command("versus"))(group_versus)
    router.message(_GROUP_CHAT, Command("karma"))(group_karma)
    router.message(_GROUP_CHAT, Command("week"))(group_week)
    router.callback_query(F.data.startswith("social:party:"))(social_party_action)
    router.callback_query(F.data.startswith("social:mirror:"))(social_mirror_action)
    router.callback_query(F.data == "social:cards:draw")(social_person_card)
    router.callback_query(F.data.startswith("social:prediction:"))(social_prediction_feedback)
    _INSTALL_MARKERS.add("group_social")
