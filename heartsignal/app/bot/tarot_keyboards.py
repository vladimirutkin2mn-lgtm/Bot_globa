"""Inline keyboards for the isolated tarot MVP flow."""

from collections.abc import Sequence
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
        + [
            [InlineKeyboardButton(text="Мои расклады", callback_data="tarot:history")],
            [InlineKeyboardButton(text="Отмена", callback_data="tarot:cancel")],
        ]
    )


def tarot_context_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без контекста", callback_data="tarot:context:skip")],
            [InlineKeyboardButton(text="Отмена", callback_data="tarot:cancel")],
        ]
    )


def tarot_result_keyboard(
    reading_id: UUID | None = None,
    price_credits: int | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if reading_id is not None and price_credits is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Открыть полный расклад за {price_credits} кр.",
                    callback_data=f"tarot:unlock:{reading_id}",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="Новый расклад", callback_data="tarot:new")],
            [InlineKeyboardButton(text="Мои расклады", callback_data="tarot:history")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tarot_full_result_keyboard() -> InlineKeyboardMarkup:
    return tarot_result_keyboard()


def tarot_insufficient_keyboard(reading_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить кредиты", callback_data="menu:balance")],
            [
                InlineKeyboardButton(
                    text="Проверить баланс и открыть",
                    callback_data=f"tarot:unlock:{reading_id}",
                )
            ],
            [InlineKeyboardButton(text="Мои расклады", callback_data="tarot:history")],
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
            [InlineKeyboardButton(text="Мои расклады", callback_data="tarot:history")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )


def tarot_history_keyboard(
    items: Sequence[tuple[UUID, str]],
    *,
    page: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=f"tarot:history:open:{reading_id}",
            )
        ]
        for reading_id, label in items
    ]
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="← Назад",
                callback_data=f"tarot:history:page:{page - 1}",
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="Вперёд →",
                callback_data=f"tarot:history:page:{page + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [InlineKeyboardButton(text="Новый расклад", callback_data="tarot:new")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
