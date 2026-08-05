"""Inline keyboards for the isolated tarot MVP flow."""

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TAROT_TOPIC_LABELS: dict[str, str] = {
    "love": "Отношения",
    "work": "Работа",
    "decision": "Выбор",
    "repeating_pattern": "Повторяющаяся ситуация",
    "general_forecast": "Общий расклад",
}


def tarot_topics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"tarot:topic:{code}",
                )
            ]
            for code, label in TAROT_TOPIC_LABELS.items()
        ]
        + [[InlineKeyboardButton(text="Отмена", callback_data="tarot:cancel")]]
    )


def tarot_context_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без контекста", callback_data="tarot:context:skip")],
            [InlineKeyboardButton(text="Отмена", callback_data="tarot:cancel")],
        ]
    )


def tarot_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Новый расклад", callback_data="tarot:new")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )


def tarot_retry_keyboard(reading_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Попробовать ещё раз",
                    callback_data=f"tarot:retry:{reading_id}",
                )
            ],
            [InlineKeyboardButton(text="Новый расклад", callback_data="tarot:new")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )
