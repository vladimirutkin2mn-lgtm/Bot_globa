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

GROUP_HELP = (
    "🔮 Numa в этом чате\n\n"
    "/card — карта дня для всего чата\n"
    "/compatibility — ответьте этой командой на сообщение другого участника\n\n"
    "Это игровые групповые механики: бот не читает историю чата и не делает выводов "
    "о чужих мыслях или чувствах."
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
    orientation = (
        SymbolOrientation.REVERSED if seed[0] & 1 else SymbolOrientation.UPRIGHT
    )
    return GroupCard(card=card, orientation=orientation)


def compatibility_for_day(first_user_id: int, second_user_id: int, for_date: date) -> CompatibilityGame:
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
        "Считайте это общей игровой темой дня — не предсказанием событий в чате."
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
            "💞 Ответьте командой /compatibility на сообщение другого участника — "
            "я соберу игровой расклад вашего дуэта на сегодня."
        )
        return

    result = compatibility_for_day(author.id, partner.id, message.date.date())
    first_name = escape(author.full_name)
    second_name = escape(partner.full_name)
    text = (
        f"💞 Игровой вайб дуэта: {first_name} × {second_name}\n\n"
        f"💬 Ритм общения — {result.communication}%\n"
        f"⚡ Спонтанность — {result.spontaneity}%\n"
        f"🤝 Совместный темп — {result.teamwork}%\n\n"
        f"Карта дуэта — {result.card.name_ru}.\n"
        f"Мотив: {result.card.upright_theme}.\n\n"
        "Это party-механика по двум аккаунтам и дате: она не определяет реальные чувства, "
        "намерения или совместимость людей."
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
