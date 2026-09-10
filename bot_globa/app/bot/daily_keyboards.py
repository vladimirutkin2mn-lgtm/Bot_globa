"""Inline controls for the optional compact solar-sign daily horoscope."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.natal_chart import ZodiacSign
from app.services.daily_sky import SIGN_LABELS


def daily_horoscope_with_sign_keyboard(
    selected_sign: ZodiacSign | None,
) -> InlineKeyboardMarkup:
    """Keep the existing daily actions while making the optional sign preference visible."""

    sign_rows: list[list[InlineKeyboardButton]]
    if selected_sign is None:
        sign_rows = [[InlineKeyboardButton(text="Выбрать свой знак", callback_data="daily:sign")]]
    else:
        sign_rows = [
            [
                InlineKeyboardButton(text="Все знаки", callback_data="daily:all"),
                InlineKeyboardButton(text="Сменить знак", callback_data="daily:sign"),
            ]
        ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *sign_rows,
            [
                InlineKeyboardButton(
                    text="✨ Что сегодня важно именно для меня?",
                    callback_data="daily:personal",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔮 Задать вопрос о сегодняшнем дне",
                    callback_data="tarot:topic:general_forecast",
                )
            ],
            [InlineKeyboardButton(text="Настройки", callback_data="daily:settings")],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
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
    if selected_sign is not None:
        rows.append(
            [InlineKeyboardButton(text="Показывать все знаки", callback_data="daily:sign:clear")]
        )
    rows.append([InlineKeyboardButton(text="← Назад к гороскопу", callback_data="menu:daily")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
