"""Shared Telegram response doubles for handler tests.

A recording session has to answer the way Telegram does, not merely record the call: the
screen contract reads the `message_id` of what it just sent in order to edit that message
next time, so a fake that answers `True` to a photo would hide a real defect.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from aiogram.methods import (
    EditMessageCaption,
    EditMessageText,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import Chat, Message, PhotoSize


def shown_texts(methods: Iterable[TelegramMethod[Any]]) -> list[str]:
    """Every piece of copy the user was shown, in order.

    A screen that is edited in place is as visible as one that was sent, so a test that
    only counted sends would read a moved screen as if nothing had happened.
    """

    shown: list[str] = []
    for method in methods:
        if isinstance(method, SendMessage | EditMessageText):
            shown.append(method.text or "")
        elif isinstance(method, SendPhoto | EditMessageCaption):
            shown.append(method.caption or "")
    return shown


def sent(method: TelegramMethod[Any], message_id: int) -> Message | None:
    """The message Telegram answers a send request with, or None for other methods."""

    if isinstance(method, SendMessage):
        return Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=int(method.chat_id), type="private"),
            text=method.text,
        )
    if isinstance(method, SendPhoto):
        return sent_photo(method, message_id)
    return None


def sent_photo(method: SendPhoto, message_id: int) -> Message:
    """Build the message Telegram would return for this `sendPhoto` request."""

    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=int(method.chat_id), type="private"),
        caption=method.caption,
        photo=[PhotoSize(file_id="scene-file-id", file_unique_id="scene", width=1, height=1)],
    )
