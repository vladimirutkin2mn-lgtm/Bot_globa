"""Transient story-continuation context and Telegram-safe direct-link callbacks."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

STORY_CONTINUATION_ID_KEY = "reading_story_continuation_id"
DIRECT_STORY_LINK_PREFIX = "stories:here:"
_GENERIC_STORY_LINK_PREFIX = "stories:link:"
_TARGET_BUTTON = "＋ Добавить в эту историю"


def continuation_story_id(data: dict[str, object]) -> UUID | None:
    value = data.get(STORY_CONTINUATION_ID_KEY)
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def direct_story_link_callback(story_id: UUID, reading_id: UUID) -> str:
    callback = (
        f"{DIRECT_STORY_LINK_PREFIX}{_compact_uuid(story_id)}:{_compact_uuid(reading_id)}"
    )
    if len(callback.encode("utf-8")) > 64:
        raise ValueError("story callback exceeds Telegram callback-data limit")
    return callback


def parse_direct_story_link(data: str | None) -> tuple[UUID, UUID] | None:
    raw = data or ""
    if not raw.startswith(DIRECT_STORY_LINK_PREFIX):
        return None
    payload = raw.removeprefix(DIRECT_STORY_LINK_PREFIX)
    parts = payload.split(":")
    if len(parts) != 2:
        return None
    story_id = _expand_uuid(parts[0])
    reading_id = _expand_uuid(parts[1])
    if story_id is None or reading_id is None:
        return None
    return story_id, reading_id


def target_story_keyboard(
    markup: InlineKeyboardMarkup,
    story_id: UUID | None,
    reading_id: UUID,
) -> InlineKeyboardMarkup:
    """Replace the generic story picker with one explicit confirmation for this story."""

    if story_id is None:
        return markup
    generic = f"{_GENERIC_STORY_LINK_PREFIX}{reading_id}"
    targeted = direct_story_link_callback(story_id, reading_id)
    rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        replaced: list[InlineKeyboardButton] = []
        for button in row:
            if button.callback_data == generic:
                replaced.append(InlineKeyboardButton(text=_TARGET_BUTTON, callback_data=targeted))
            else:
                replaced.append(button)
        rows.append(replaced)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _compact_uuid(value: UUID) -> str:
    return urlsafe_b64encode(value.bytes).decode("ascii").rstrip("=")


def _expand_uuid(value: str) -> UUID | None:
    if len(value) != 22:
        return None
    try:
        raw = urlsafe_b64decode(f"{value}==".encode("ascii"))
        return UUID(bytes=raw) if len(raw) == 16 else None
    except (Base64Error, UnicodeEncodeError, ValueError):
        return None
