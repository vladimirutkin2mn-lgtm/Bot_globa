"""Explicit, privacy-safe group party mechanics for organic sharing.

The group layer deliberately does not read ordinary chat messages, enumerate members,
persist chat/member data, or call the LLM. Every result is a deterministic game outcome
for the UTC date carried by the Telegram update, so retries in the same chat do not
produce a more dramatic answer until somebody likes it.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art
from app.domain.reading import SymbolOrientation
from app.domain.tarot import RWS_78_V1, TarotCard

router = Router(name="group_virality")
_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})

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
    "Кто сегодня первым предложит план, на который остальные неожиданно согласятся?",
    "Кто сегодня лучше всех умеет превратить хаос в хороший сюжет?",
    "Кому сегодня доверили бы выбрать место без долгих обсуждений?",
    "Кто сегодня скорее всех скажет: «ладно, делаем» — и запустит движение?",
    "Кто сегодня главный хранитель здравого смысла, когда остальных понесёт?",
    "Кто сегодня способен придумать самый неожиданный, но рабочий поворот?",
)

GROUP_HELP = (
    "🔮 Numa в этом чате\n\n"
    "Команды:\n\n"
    "🔮 /card — карта дня для всего чата\n"
    "💞 /compatibility — вайб двух участников на сегодня\n"
    "🎉 /party — игра «Кто сегодня кто?»\n"
    "🃏 /event — расклад на вечер, поездку или событие\n"
    "✨ /grouphelp — показать эту подсказку\n\n"
    "Как использовать:\n"
    "• /compatibility — ответьте командой на сообщение человека.\n"
    "• /event — после команды напишите: вечер, поездка или событие.\n\n"
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
class PartyPromptGame:
    prompt: str
    archetype: TarotCard


@dataclass(frozen=True, slots=True)
class GroupEventSpread:
    event_kind: str
    cards: tuple[TarotCard, TarotCard, TarotCard]


def _digest(*parts: object) -> bytes:
    payload = ":".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode()).digest()


def group_card_for_day(chat_id: int, for_date: date) -> GroupCard:
    """Return one stable RWS card for a chat/date without storing the chat id."""

    seed = _digest("group-card-v1", chat_id, for_date.isoformat())
    card = min(
        RWS_78_V1.cards,
        key=lambda candidate: _digest(seed.hex(), candidate.code),
    )
    orientation = SymbolOrientation.REVERSED if seed[0] & 1 else SymbolOrientation.UPRIGHT
    return GroupCard(card=card, orientation=orientation)


def compatibility_for_day(
    first_user_id: int, second_user_id: int, for_date: date
) -> CompatibilityGame:
    """Create a symmetric party-game result for two Telegram users and one date."""

    left, right = sorted((first_user_id, second_user_id))
    seed = _digest("group-compatibility-v1", left, right, for_date.isoformat())

    def score(offset: int) -> int:
        # A playful range: enough variation to be shareable without pretending to be a
        # diagnostic measurement or engineering artificial 0/100 drama.
        return 45 + seed[offset] % 51

    card = RWS_78_V1.cards[int.from_bytes(seed[3:5], "big") % len(RWS_78_V1.cards)]
    return CompatibilityGame(
        communication=score(0),
        spontaneity=score(1),
        teamwork=score(2),
        card=card,
    )


def party_prompt_for_day(chat_id: int, for_date: date) -> PartyPromptGame:
    """Return a stable self-nomination prompt; never select a group member for the chat."""

    seed = _digest("group-party-v1", chat_id, for_date.isoformat())
    prompt = PARTY_PROMPTS[seed[0] % len(PARTY_PROMPTS)]
    archetype = RWS_78_V1.cards[int.from_bytes(seed[1:3], "big") % len(RWS_78_V1.cards)]
    return PartyPromptGame(prompt=prompt, archetype=archetype)


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
    keyboard = (
        _private_keyboard(username, persona="love", label="💞 Разобрать отношения лично")
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


@router.message(_GROUP_CHAT, Command("party"))
async def party_prompt(message: Message, bot: Bot) -> None:
    result = party_prompt_for_day(message.chat.id, message.date.date())
    text = (
        "🎉 Кто сегодня кто?\n\n"
        f"{result.prompt}\n\n"
        f"Архетип чата сегодня — {result.archetype.name_ru}.\n"
        f"Мотив: {result.archetype.upright_theme}.\n\n"
        "Выберите героя сами 👀"
    )
    username = await _bot_username(bot)
    keyboard = (
        _private_keyboard(username, persona="tarot", label="🔮 Узнать свой архетип")
        if username
        else None
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.archetype.code),
        text,
        reply_markup=keyboard,
    )


@router.message(_GROUP_CHAT, Command("event"))
async def group_event(message: Message, bot: Bot) -> None:
    event_kind = _event_kind_from_command(message)
    if event_kind is None:
        await message.answer("🃏 Что смотрим?\n\n/event вечер\n/event поездка\n/event событие")
        return

    result = group_event_spread_for_day(message.chat.id, message.date.date(), event_kind)
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
        + "\n\nКарты этого расклада не меняются до завтра ✨"
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
        card_art(result.cards[0].code),
        text,
        reply_markup=keyboard,
    )
