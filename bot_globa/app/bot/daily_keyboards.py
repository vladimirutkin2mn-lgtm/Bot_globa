"""Inline controls for the optional compact solar-sign daily horoscope."""

from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.natal_chart import ZodiacSign
from app.services.daily_sky import SIGN_LABELS

DAILY_PERSONAL_CALLBACK = "daily:personal"
DAILY_SHARE_CALLBACK = "daily:share"


def daily_personal_callback(delivery_date: date | None = None) -> str:
    """Keep legacy menu callbacks while dating scheduled-digest CTAs."""

    if delivery_date is None:
        return DAILY_PERSONAL_CALLBACK
    return f"{DAILY_PERSONAL_CALLBACK}:{delivery_date.isoformat()}"


def daily_horoscope_with_sign_keyboard(
    selected_sign: ZodiacSign | None,
    delivery_date: date | None = None,
) -> InlineKeyboardMarkup:
    """Keep only the two product actions visible on the forecast itself."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Что сегодня важно именно для меня?",
                    callback_data=daily_personal_callback(delivery_date),
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Поделиться темой дня",
                    callback_data=DAILY_SHARE_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(text="Ещё", callback_data="daily:more"),
                InlineKeyboardButton(text="← В меню", callback_data="menu:home"),
            ],
        ]
    )


def daily_more_keyboard(selected_sign: ZodiacSign | None) -> InlineKeyboardMarkup:
    """Move secondary daily controls off the forecast without removing them."""

    sign_text = "Выбрать свой знак" if selected_sign is None else "Сменить знак"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=sign_text, callback_data="daily:sign"),
                InlineKeyboardButton(text="Все знаки", callback_data="daily:all"),
            ],
            [
                InlineKeyboardButton(
                    text="🔮 Задать вопрос о сегодняшнем дне",
                    callback_data="tarot:topic:general_forecast",
                )
            ],
            [InlineKeyboardButton(text="Настройки", callback_data="daily:settings")],
            [InlineKeyboardButton(text="← К прогнозу", callback_data="menu:daily")],
        ]
    )


def daily_sign_keyboard(selected_sign: ZodiacSign | None) -> InlineKeyboardMarkup:
    """Choose a solar sign without collecting birth date, place or time."""

    buttons: list[InlineKeyboardButton] = []
    for sign in ZodiacSign:
        emoji, name = SIGN_LABELS[sign]
        prefix = "✓ " if sign is selected_sign else ""
        buttons.append(
            InlineKeyboardButton(
                text=f"{prefix}{emoji} {name}",
                callback_data=f"daily:sign:{sign.value}",
            )
        )
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="Все знаки", callback_data="daily:all")])
    rows.append([InlineKeyboardButton(text="← Назад к гороскопу", callback_data="menu:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
