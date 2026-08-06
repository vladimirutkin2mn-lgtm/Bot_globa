"""Inline keyboards for explicit oracle-memory controls."""

# ruff: noqa: RUF001

from collections.abc import Sequence
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def memory_disabled_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Включить память", callback_data="memory:grant")],
            [InlineKeyboardButton(text="Главное меню", callback_data="memory:menu")],
        ]
    )


def memory_enabled_keyboard(has_items: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_items:
        rows.extend(
            [
                [InlineKeyboardButton(text="Что бот помнит", callback_data="memory:list:0")],
                [
                    InlineKeyboardButton(
                        text="Удалить всю память",
                        callback_data="memory:clear:prompt",
                    )
                ],
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="Отключить память",
                    callback_data="memory:revoke:prompt",
                )
            ],
            [InlineKeyboardButton(text="Главное меню", callback_data="memory:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def memory_list_keyboard(
    items: Sequence[tuple[UUID, int]],
    *,
    page: int,
    has_previous: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{ordinal} · Изменить или удалить",
                callback_data=f"memory:open:{item_id}:{page}",
            )
        ]
        for item_id, ordinal in items
    ]
    navigation: list[InlineKeyboardButton] = []
    if has_previous:
        navigation.append(
            InlineKeyboardButton(text="← Назад", callback_data=f"memory:list:{page - 1}")
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(text="Вперёд →", callback_data=f"memory:list:{page + 1}")
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [InlineKeyboardButton(text="Настройки памяти", callback_data="memory:home")],
            [InlineKeyboardButton(text="Главное меню", callback_data="memory:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def memory_item_keyboard(item_id: UUID, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Исправить",
                    callback_data=f"memory:edit:{item_id}:{page}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"memory:delete:prompt:{item_id}:{page}",
                )
            ],
            [InlineKeyboardButton(text="Назад к списку", callback_data=f"memory:list:{page}")],
        ]
    )


def memory_edit_cancel_keyboard(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=f"memory:edit:cancel:{page}")]
        ]
    )


def memory_delete_confirmation_keyboard(item_id: UUID, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"memory:delete:confirm:{item_id}:{page}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"memory:open:{item_id}:{page}",
                )
            ],
        ]
    )


def memory_clear_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить все записи",
                    callback_data="memory:clear:confirm",
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="memory:home")],
        ]
    )


def memory_revoke_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, отключить и удалить",
                    callback_data="memory:revoke:confirm",
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="memory:home")],
        ]
    )
