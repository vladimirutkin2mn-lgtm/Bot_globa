"""Explicit, privacy-safe group party mechanics for organic sharing.

The group layer deliberately does not read ordinary chat messages, enumerate members,
persist chat/member data, or call the LLM. Results are deterministic games for one UTC
date, so retries do not keep drawing until a more dramatic answer appears.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art
from app.domain.reading import SymbolOrientation
from app.domain.tarot import RWS_78_V1, TarotCard

router = Router(name="group_virality")
_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}

GROUP_EVENT_KINDS: dict[str, str] = {
    "вечер": "вечер",
    "поездка": "поездку",
    "событие": "событие",
}
EVENT_POSITION_LABELS = (
    "Тон события",
    "Что поможет быть на одной волне",
    "На что обратить внимание",
)
PARTY_PROMPTS = (
    "Кто сегодня вероятнее всех внезапно напишет бывшему? 👀",
    "Кто сегодня первым предложит план, на который остальные неожиданно согласятся?",
    "Кто сегодня потратит больше всех на то, чего вообще не было в планах?",
    "Кто сегодня лучше всех умеет превратить хаос в хороший сюжет?",
    "Кто сегодня первым скажет: «ладно, делаем» — и запустит движение?",
    "Кто сегодня окажется прав в споре, но поймёт это слишком поздно?",
    "Кто сегодня способен придумать самый неожиданный, но рабочий поворот?",
    "Кто сегодня первым предложит идею, которая сначала покажется сомнительной?",
    "Кто сегодня главный хранитель здравого смысла, когда остальных понесёт?",
    "Кто сегодня скорее всех устроит маленькое приключение на ровном месте?",
    "Кто сегодня первым исчезнет со словами «я на пять минут»?",
    "Кому сегодня опаснее всего давать право выбирать, куда идти дальше?",
)
PARTY_VIBES = (
    ("Авантюра", "Сегодня кто-то обязательно предложит идею, которой не было в плане."),
    ("Флирт", "Без двусмысленных сообщений сегодня может не обойтись 👀"),
    ("Откровения", "Есть шанс услышать фразу, которую давно собирались сказать."),
    ("Хаос", "Планы сегодня особенно хорошо работают до первого неожиданного сообщения."),
    ("Ностальгия", "Кто-то обязательно вспомнит историю, которую все уже знают наизусть."),
    ("Спонтанность", "Лучший момент дня может начаться со слов: «а давайте прямо сейчас»."),
    ("Примирение", "Сегодня проще обычного перестать спорить о том, кто был прав."),
    ("Плохие идеи", "Самые сомнительные предложения сегодня звучат подозрительно убедительно."),
)

GROUP_HELP = (
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
    "Все групповые расклады — игровой формат. Личные вопросы лучше задавать Numa один на один."
)


@dataclass(frozen=True, slots=True)
class GroupCard:
    card: TarotCard
    orientation: SymbolOrientation

    @property
    def theme(self) -> str:
        if self.orientation is SymbolOrientation.REVERSED:
            return self.card.reversed_theme
        return self.card.upright_theme


@dataclass(frozen=True, slots=True)
class CompatibilityGame:
    communication: int
    spontaneity: int
    teamwork: int
    card: TarotCard


@dataclass(frozen=True, slots=True)
class DuelGame:
    first_card: TarotCard
    second_card: TarotCard
    dynamic_card: TarotCard


@dataclass(frozen=True, slots=True)
class PartyPromptGame:
    prompt: str
    archetype: TarotCard


@dataclass(frozen=True, slots=True)
class PartyVibe:
    title: str
    text: str
    card: TarotCard


@dataclass(frozen=True, slots=True)
class GroupEventSpread:
    event_kind: str
    cards: tuple[TarotCard, TarotCard, TarotCard]


def _digest(*parts: object) -> bytes:
    payload = ":".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode()).digest()


def _stable_card(namespace: str, *parts: object) -> TarotCard:
    seed = _digest(namespace, *parts)
    return RWS_78_V1.cards[int.from_bytes(seed[:4], "big") % len(RWS_78_V1.cards)]


def group_card_for_day(chat_id: int, for_date: date) -> GroupCard:
    """Return one stable RWS card for a chat/date without storing the chat id."""

    seed = _digest("group-card-v1", chat_id, for_date.isoformat())
    card = min(
        RWS_78_V1.cards,
        key=lambda candidate: _digest(seed.hex(), candidate.code),
    )
    orientation = SymbolOrientation.REVERSED if seed[0] & 1 else SymbolOrientation.UPRIGHT
    return GroupCard(card=card, orientation=orientation)


def chat_archetype_for_day(chat_id: int, for_date: date) -> TarotCard:
    """Return a stable daily archetype that is intentionally separate from /card."""

    return _stable_card("group-chat-archetype-v1", chat_id, for_date.isoformat())


def compatibility_for_day(
    first_user_id: int, second_user_id: int, for_date: date
) -> CompatibilityGame:
    """Create a symmetric party-game result for two Telegram users and one date."""

    left, right = sorted((first_user_id, second_user_id))
    seed = _digest("group-compatibility-v1", left, right, for_date.isoformat())

    def score(offset: int) -> int:
        return 45 + seed[offset] % 51

    card = RWS_78_V1.cards[int.from_bytes(seed[3:5], "big") % len(RWS_78_V1.cards)]
    return CompatibilityGame(
        communication=score(0),
        spontaneity=score(1),
        teamwork=score(2),
        card=card,
    )


def duel_for_day(first_user_id: int, second_user_id: int, for_date: date) -> DuelGame:
    """Give each participant one stable card plus one symmetric card for the dynamic."""

    if first_user_id == second_user_id:
        raise ValueError("duel requires two users")

    first_card = _stable_card("group-duel-person-v1", first_user_id, for_date.isoformat())
    second_candidates = [card for card in RWS_78_V1.cards if card != first_card]
    second_seed = _digest("group-duel-person-v1", second_user_id, for_date.isoformat())
    second_card = second_candidates[int.from_bytes(second_seed[:4], "big") % len(second_candidates)]

    left, right = sorted((first_user_id, second_user_id))
    dynamic_candidates = [card for card in RWS_78_V1.cards if card not in {first_card, second_card}]
    dynamic_seed = _digest("group-duel-dynamic-v1", left, right, for_date.isoformat())
    dynamic_card = dynamic_candidates[
        int.from_bytes(dynamic_seed[:4], "big") % len(dynamic_candidates)
    ]
    return DuelGame(
        first_card=first_card,
        second_card=second_card,
        dynamic_card=dynamic_card,
    )


def party_prompt_for_day(chat_id: int, for_date: date, round_index: int = 0) -> PartyPromptGame:
    """Return a stable prompt; later rounds rotate without selecting a member."""

    if round_index < 0:
        raise ValueError("round index must be non-negative")
    seed = _digest("group-party-v2", chat_id, for_date.isoformat())
    prompt_index = (seed[0] + round_index) % len(PARTY_PROMPTS)
    prompt = PARTY_PROMPTS[prompt_index]
    archetype = _stable_card("group-party-archetype-v2", chat_id, for_date.isoformat(), round_index)
    return PartyPromptGame(prompt=prompt, archetype=archetype)


def party_vibe_for_day(chat_id: int, for_date: date) -> PartyVibe:
    """Return one stable conversational theme for the group evening."""

    seed = _digest("group-party-vibe-v1", chat_id, for_date.isoformat())
    title, text = PARTY_VIBES[seed[0] % len(PARTY_VIBES)]
    card = _stable_card("group-party-vibe-card-v1", chat_id, for_date.isoformat())
    return PartyVibe(title=title, text=text, card=card)


def group_event_spread_for_day(chat_id: int, for_date: date, event_kind: str) -> GroupEventSpread:
    """Return three unique deterministic cards for one fixed, non-free-form event kind."""

    if event_kind not in GROUP_EVENT_KINDS:
        raise ValueError("unsupported group event kind")
    seed = _digest("group-event-v1", chat_id, for_date.isoformat(), event_kind)
    cards = sorted(
        RWS_78_V1.cards,
        key=lambda candidate: _digest(seed.hex(), candidate.code),
    )[:3]
    return GroupEventSpread(event_kind=event_kind, cards=(cards[0], cards[1], cards[2]))


def private_deep_link(bot_username: str, persona: str) -> str:
    """Build only one of the existing fixed persona deep links."""

    if persona not in {"tarot", "love"}:
        raise ValueError("unsupported group deep-link destination")
    username = bot_username.removeprefix("@").strip()
    if not username:
        raise ValueError("bot username is required")
    return f"https://t.me/{username}?start={persona}"


def _private_keyboard(bot_username: str, *, persona: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, url=private_deep_link(bot_username, persona))]
        ]
    )


def _append_back(
    keyboard: InlineKeyboardMarkup | None,
    *,
    text: str,
    callback_data: str,
) -> InlineKeyboardMarkup:
    rows = [] if keyboard is None else [list(row) for row in keyboard.inline_keyboard]
    rows.append([InlineKeyboardButton(text=text, callback_data=callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _party_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Кто сегодня…", callback_data="group:party:who:0")],
            [
                InlineKeyboardButton(text="🎭 Архетип чата", callback_data="group:party:archetype"),
                InlineKeyboardButton(text="🔥 Тема вечера", callback_data="group:party:vibe"),
            ],
        ]
    )


def _event_picker_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌙 Вечер", callback_data="group:event:вечер"),
                InlineKeyboardButton(text="✈️ Поездка", callback_data="group:event:поездка"),
            ],
            [InlineKeyboardButton(text="✨ Событие", callback_data="group:event:событие")],
        ]
    )


def _compatibility_keyboard(
    bot_username: str | None, first_user_id: int, second_user_id: int
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="⚔️ Дуэль дня",
                callback_data=f"group:duel:{first_user_id}:{second_user_id}",
            )
        ]
    ]
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💞 Разобрать отношения лично",
                    url=private_deep_link(bot_username, "love"),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _party_result_keyboard(bot_username: str | None, next_round: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🎲 Ещё вопрос",
                callback_data=f"group:party:who:{next_round}",
            )
        ]
    ]
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔮 Что сегодня про меня?",
                    url=private_deep_link(bot_username, "tarot"),
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _bot_username(bot: Bot) -> str | None:
    me = await bot.get_me()
    return me.username


def _event_kind_from_command(message: Message) -> str | None:
    text = message.text
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    candidate = parts[1].strip().casefold()
    return candidate if candidate in GROUP_EVENT_KINDS else None


def _callback_group_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    if not isinstance(message, Message):
        return None
    if message.chat.type not in _GROUP_TYPES:
        return None
    return message


def _today_utc() -> date:
    return datetime.now(UTC).date()


async def _send_chat_archetype(
    message: Message,
    bot: Bot,
    *,
    for_date: date,
    back_to_party: bool = False,
) -> None:
    card = chat_archetype_for_day(message.chat.id, for_date)
    text = (
        "🎭 Архетип этого чата сегодня\n\n"
        f"{card.name_ru}\n"
        f"Главный мотив — {card.upright_theme}.\n\n"
        "Кто первым подхватит эту энергию? 👀"
    )
    username = await _bot_username(bot)
    keyboard = (
        _private_keyboard(username, persona="tarot", label="🔮 Узнать свой архетип")
        if username
        else None
    )
    if back_to_party:
        keyboard = _append_back(
            keyboard,
            text="← К играм",
            callback_data="group:party:menu",
        )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=keyboard,
    )


async def _send_party_question(
    message: Message, bot: Bot, *, for_date: date, round_index: int
) -> None:
    result = party_prompt_for_day(message.chat.id, for_date, round_index)
    text = (
        "🎲 Кто сегодня…\n\n"
        f"{result.prompt}\n\n"
        "Тегайте кандидатов. Numa никого не назначает сама 👀"
    )
    username = await _bot_username(bot)
    await send_art(
        bot,
        message.chat.id,
        card_art(result.archetype.code),
        text,
        reply_markup=_party_result_keyboard(username, round_index + 1),
    )


async def _send_party_vibe(
    message: Message,
    bot: Bot,
    *,
    for_date: date,
    back_to_party: bool = False,
) -> None:
    result = party_vibe_for_day(message.chat.id, for_date)
    text = (
        "🔥 Тема этого вечера\n\n"
        f"{result.title}\n"
        f"{result.text}\n\n"
        "Вопрос только в том, кто первым это запустит 👀"
    )
    username = await _bot_username(bot)
    keyboard = (
        _private_keyboard(username, persona="tarot", label="🔮 Что ждёт лично меня?")
        if username
        else None
    )
    if back_to_party:
        keyboard = _append_back(
            keyboard,
            text="← К играм",
            callback_data="group:party:menu",
        )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.card.code),
        text,
        reply_markup=keyboard,
    )


async def _send_event_result(
    message: Message,
    bot: Bot,
    *,
    for_date: date,
    event_kind: str,
    back_to_picker: bool = False,
) -> None:
    result = group_event_spread_for_day(message.chat.id, for_date, event_kind)
    label = GROUP_EVENT_KINDS[result.event_kind]
    lines = [
        f"{index}. {position} — {card.name_ru}: {card.upright_theme}."
        for index, (position, card) in enumerate(
            zip(EVENT_POSITION_LABELS, result.cards, strict=True),
            start=1,
        )
    ]
    text = (
        f"🃏 Расклад на {label}\n\n"
        + "\n".join(lines)
        + "\n\nА что это событие принесёт лично вам?"
    )
    username = await _bot_username(bot)
    keyboard = (
        _private_keyboard(username, persona="tarot", label="🔮 Личный расклад")
        if username
        else None
    )
    if back_to_picker:
        keyboard = _append_back(
            keyboard,
            text="← К выбору события",
            callback_data="group:event:menu",
        )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.cards[0].code),
        text,
        reply_markup=keyboard,
    )


@router.message(_GROUP_CHAT, Command("grouphelp"))
async def group_help(message: Message) -> None:
    await message.answer(GROUP_HELP)


@router.message(_GROUP_CHAT, Command("card"))
async def group_card(message: Message, bot: Bot) -> None:
    result = group_card_for_day(message.chat.id, message.date.date())
    orientation = "перевёрнутая" if result.orientation is SymbolOrientation.REVERSED else "прямая"
    text = (
        "🔮 Карта дня этого чата\n\n"
        f"{result.card.name_ru} · {orientation}\n"
        f"Сегодняшний мотив: {result.theme}.\n\n"
        "Пусть это будет вашей общей темой дня ✨"
    )
    username = await _bot_username(bot)
    keyboard = (
        _private_keyboard(username, persona="tarot", label="🔮 Сделать личный расклад")
        if username
        else None
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.card.code),
        text,
        reply_markup=keyboard,
    )


@router.message(_GROUP_CHAT, Command("chat"))
async def group_chat_archetype(message: Message, bot: Bot) -> None:
    await _send_chat_archetype(message, bot, for_date=message.date.date())


@router.message(_GROUP_CHAT, Command("compatibility"))
async def compatibility(message: Message, bot: Bot) -> None:
    author = message.from_user
    replied = message.reply_to_message
    partner = replied.from_user if replied is not None else None
    if author is None:
        return
    if partner is None or partner.is_bot or partner.id == author.id:
        await message.answer(
            "💞 Чтобы посмотреть вайб вашего дуэта, ответьте /compatibility "
            "на сообщение другого участника."
        )
        return

    result = compatibility_for_day(author.id, partner.id, message.date.date())
    first_name = escape(author.full_name)
    second_name = escape(partner.full_name)
    text = (
        f"💞 Вайб дуэта на сегодня: {first_name} × {second_name}\n\n"
        f"💬 Ритм общения — {result.communication}%\n"
        f"⚡ Спонтанность — {result.spontaneity}%\n"
        f"🤝 Совместный темп — {result.teamwork}%\n\n"
        f"Карта дуэта — {result.card.name_ru}.\n"
        f"Мотив: {result.card.upright_theme}.\n\n"
        "Игровой расклад на сегодня — не оценка реальных чувств."
    )
    username = await _bot_username(bot)
    await send_art(
        bot,
        message.chat.id,
        card_art(result.card.code),
        text,
        reply_markup=_compatibility_keyboard(username, author.id, partner.id),
    )


@router.callback_query(F.data.startswith("group:duel:"))
async def compatibility_duel(callback: CallbackQuery, bot: Bot) -> None:
    message = _callback_group_message(callback)
    data = callback.data
    if message is None or data is None:
        await callback.answer()
        return

    try:
        _, _, raw_first, raw_second = data.split(":", 3)
        first_user_id = int(raw_first)
        second_user_id = int(raw_second)
    except (TypeError, ValueError):
        await callback.answer("Не получилось открыть дуэль.")
        return

    viewer_id = callback.from_user.id
    if viewer_id not in {first_user_id, second_user_id}:
        await callback.answer("Эту дуэль могут открыть только участники пары.")
        return

    other_id = second_user_id if viewer_id == first_user_id else first_user_id
    result = duel_for_day(viewer_id, other_id, _today_utc())
    text = (
        "⚔️ Дуэль дня\n\n"
        f"Твоя энергия — {result.first_card.name_ru}: {result.first_card.upright_theme}.\n\n"
        f"Энергия второго участника — {result.second_card.name_ru}: "
        f"{result.second_card.upright_theme}.\n\n"
        f"Между вами — {result.dynamic_card.name_ru}: {result.dynamic_card.upright_theme}.\n\n"
        "Посмотрим глубже один на один?"
    )
    username = await _bot_username(bot)
    keyboard = (
        _private_keyboard(username, persona="love", label="💞 Разобрать динамику лично")
        if username
        else None
    )
    await callback.answer()
    await send_art(
        bot,
        message.chat.id,
        card_art(result.dynamic_card.code),
        text,
        reply_markup=keyboard,
    )


@router.message(_GROUP_CHAT, Command("party"))
async def party_menu(message: Message) -> None:
    await message.answer(
        "🎉 Во что играем?\n\nВыберите механику — Numa запустит её прямо в этом чате.",
        reply_markup=_party_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("group:party:"))
async def party_action(callback: CallbackQuery, bot: Bot) -> None:
    message = _callback_group_message(callback)
    data = callback.data
    if message is None or data is None:
        await callback.answer()
        return

    action = data.removeprefix("group:party:")
    await callback.answer()
    if action == "menu":
        await message.answer(
            "🎉 Во что играем?\n\nВыберите механику — Numa запустит её прямо в этом чате.",
            reply_markup=_party_menu_keyboard(),
        )
        return
    if action == "archetype":
        await _send_chat_archetype(
            message,
            bot,
            for_date=_today_utc(),
            back_to_party=True,
        )
        return
    if action == "vibe":
        await _send_party_vibe(
            message,
            bot,
            for_date=_today_utc(),
            back_to_party=True,
        )
        return
    if action.startswith("who:"):
        try:
            round_index = int(action.partition(":")[2])
        except ValueError:
            return
        if not 0 <= round_index <= 99:
            return
        await _send_party_question(
            message,
            bot,
            for_date=_today_utc(),
            round_index=round_index,
        )


@router.message(_GROUP_CHAT, Command("event"))
async def group_event(message: Message, bot: Bot) -> None:
    event_kind = _event_kind_from_command(message)
    if event_kind is None:
        await message.answer(
            "🃏 На что делаем расклад?",
            reply_markup=_event_picker_keyboard(),
        )
        return
    await _send_event_result(
        message,
        bot,
        for_date=message.date.date(),
        event_kind=event_kind,
    )


@router.callback_query(F.data.startswith("group:event:"))
async def group_event_button(callback: CallbackQuery, bot: Bot) -> None:
    message = _callback_group_message(callback)
    data = callback.data
    if message is None or data is None:
        await callback.answer()
        return
    event_kind = data.removeprefix("group:event:").casefold()
    if event_kind == "menu":
        await callback.answer()
        await message.answer(
            "🃏 На что делаем расклад?",
            reply_markup=_event_picker_keyboard(),
        )
        return
    if event_kind not in GROUP_EVENT_KINDS:
        await callback.answer("Такого расклада здесь нет.")
        return
    await callback.answer()
    await _send_event_result(
        message,
        bot,
        for_date=_today_utc(),
        event_kind=event_kind,
        back_to_picker=True,
    )
