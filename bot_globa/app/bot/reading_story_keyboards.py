"""Telegram keyboards for user-managed reading stories."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.reading_story import ReadingStoryView


@dataclass(frozen=True, slots=True)
class StoryReadingButton:
    reading_id: UUID
    label: str
    open_callback: str


def _compact_title(title: str, limit: int = 46) -> str:
    return title if len(title) <= limit else f"{title[: limit - 1].rstrip()}…"


def stories_hub_keyboard(stories: Sequence[ReadingStoryView]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"📖 {_compact_title(story.title)}",
                callback_data=f"stories:open:{story.id}:0",
            )
        ]
        for story in stories
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="＋ Новая история", callback_data="stories:create")],
            [InlineKeyboardButton(text="🗂 Все разборы", callback_data="stories:all")],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def story_all_readings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔮 Таролог", callback_data="tarot:history")],
            [InlineKeyboardButton(text="💞 Любовный оракул", callback_data="love:history")],
            [InlineKeyboardButton(text="🌙 Мистический психолог", callback_data="psy:history")],
            [InlineKeyboardButton(text="🪐 Астролог", callback_data="astro:history")],
            [InlineKeyboardButton(text="← К историям", callback_data="menu:readings")],
        ]
    )


def story_title_cancel_keyboard(story_id: UUID | None = None) -> InlineKeyboardMarkup:
    callback = "menu:readings" if story_id is None else f"stories:open:{story_id}:0"
    label = "← К историям" if story_id is None else "← Назад к истории"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=callback)]]
    )


def story_detail_keyboard(
    story_id: UUID,
    readings: Sequence[StoryReadingButton],
    *,
    page: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for reading in readings:
        rows.append(
            [
                InlineKeyboardButton(text=reading.label, callback_data=reading.open_callback),
                InlineKeyboardButton(
                    text="✕",
                    callback_data=f"stories:unlink:{reading.reading_id}",
                ),
            ]
        )
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="← Назад",
                callback_data=f"stories:open:{story_id}:{page - 1}",
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="Вперёд →",
                callback_data=f"stories:open:{story_id}:{page + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="＋ Добавить разбор",
                    callback_data=f"stories:add:{story_id}:0",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Переименовать",
                    callback_data=f"stories:rename:{story_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"stories:delete:{story_id}",
                ),
            ],
            [InlineKeyboardButton(text="← К историям", callback_data="menu:readings")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def story_add_readings_keyboard(
    story_id: UUID,
    readings: Sequence[StoryReadingButton],
    *,
    page: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=reading.label,
                callback_data=f"stories:pick:{reading.reading_id}",
            )
        ]
        for reading in readings
    ]
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="← Назад",
                callback_data=f"stories:add:{story_id}:{page - 1}",
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="Вперёд →",
                callback_data=f"stories:add:{story_id}:{page + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад к истории",
                callback_data=f"stories:open:{story_id}:0",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def story_delete_confirmation_keyboard(story_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить историю",
                    callback_data=f"stories:delete:yes:{story_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="← Отмена",
                    callback_data=f"stories:open:{story_id}:0",
                )
            ],
        ]
    )
