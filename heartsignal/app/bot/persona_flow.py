"""Declarative description of one persona's Telegram reading flow.

A flow owns everything that differs between personas — callback namespace, FSM states,
copy and keyboards — so `app.bot.persona_handlers` can stay persona-neutral.
"""

# ruff: noqa: RUF001

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from aiogram.fsm.state import State
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.reading_renderer import ReadingCopy
from app.services.monetized_reading import MonetizedReadingService
from app.services.persona_reading import PersonaReadingUseCase

MENU_BUTTON = "Главное меню"
CANCEL_BUTTON = "Отмена"
SKIP_CONTEXT_BUTTON = "Без контекста"
RETRY_BUTTON = "Попробовать ещё раз"
BUY_CREDITS_BUTTON = "Купить кредиты"
CHECK_BALANCE_BUTTON = "Проверить баланс и открыть"

NOT_ONBOARDED = "Сначала отправьте /start и завершите подтверждение возраста и условий."
INVALID_TEXT = "Нужно обычное текстовое сообщение допустимой длины."
QUESTION_PROMPT = (
    "Напишите один конкретный вопрос. Лучше спрашивать о возможных сценариях, своих решениях "
    "и следующем шаге, а не о гарантированном будущем или чужих тайных мыслях."
)
CONTEXT_PROMPT = (
    "Можно добавить короткий контекст ситуации одним сообщением или продолжить без него."
)
UNLOCKING = "Проверяю баланс и открываю полный разбор…"
INSUFFICIENT = "Для полного разбора нужно {price} кр. Доступный баланс: {balance} кр."

QUESTION_LIMIT = 8000
CONTEXT_LIMIT = 12000


class ReadingStates(Protocol):
    """The three FSM states every reading intake goes through.

    Each persona needs its own `StatesGroup` subclass: aiogram identifies a state by its
    group's class name, and two flows sharing one group would answer each other's updates.
    """

    waiting_for_question: State
    waiting_for_context: State
    generating: State


@dataclass(frozen=True, slots=True)
class PersonaFlowTexts:
    """Copy that genuinely differs between personas."""

    welcome: str
    processing: str
    opening: str
    already_processing: str
    unavailable: str
    failed: str
    history_title: str
    history_empty: str
    history_fallback: str
    locked: str
    unlock_failed: str
    unlock_button: str
    new_button: str
    history_button: str


@dataclass(frozen=True, slots=True)
class PersonaFlow:
    """One persona's transport contract: namespace, states, copy and keyboards."""

    persona_code: str
    namespace: str
    states: type[ReadingStates]
    topic_labels: Mapping[str, str]
    texts: PersonaFlowTexts
    copy: ReadingCopy

    def callback(self, *parts: str) -> str:
        """Build a callback payload; Telegram allows 64 bytes, so namespaces stay short."""
        return ":".join((self.namespace, *parts))

    def topics_keyboard(self) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(text=label, callback_data=self.callback("topic", code))]
            for code, label in self.topic_labels.items()
        ]
        rows.append(
            [InlineKeyboardButton(text=self.texts.history_button, callback_data=self._history)]
        )
        rows.append([InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=self._cancel)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def context_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=SKIP_CONTEXT_BUTTON,
                        callback_data=self.callback("context", "skip"),
                    )
                ],
                [InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=self._cancel)],
            ]
        )

    def handoff_keyboard(self) -> InlineKeyboardMarkup:
        """Do not invite another mystical action from an active safety handoff."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
            ]
        )

    def result_keyboard(
        self,
        reading_id: UUID | None = None,
        price_credits: int | None = None,
    ) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if reading_id is not None and price_credits is not None:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=self.texts.unlock_button.format(price=price_credits),
                        callback_data=self.callback("unlock", str(reading_id)),
                    )
                ]
            )
        rows.extend(self._navigation_rows())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def insufficient_keyboard(self, reading_id: UUID) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=BUY_CREDITS_BUTTON, callback_data="menu:balance")],
                [
                    InlineKeyboardButton(
                        text=CHECK_BALANCE_BUTTON,
                        callback_data=self.callback("unlock", str(reading_id)),
                    )
                ],
                [InlineKeyboardButton(text=self.texts.history_button, callback_data=self._history)],
                [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
            ]
        )

    def retry_keyboard(self, reading_id: UUID) -> InlineKeyboardMarkup:
        rows = [
            [
                InlineKeyboardButton(
                    text=RETRY_BUTTON,
                    callback_data=self.callback("retry", str(reading_id)),
                )
            ]
        ]
        rows.extend(self._navigation_rows())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def history_keyboard(
        self,
        items: Sequence[tuple[UUID, str]],
        *,
        page: int,
        has_next: bool,
    ) -> InlineKeyboardMarkup:
        rows = [
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=self.callback("history", "open", str(reading_id)),
                )
            ]
            for reading_id, label in items
        ]
        navigation: list[InlineKeyboardButton] = []
        if page > 0:
            navigation.append(
                InlineKeyboardButton(
                    text="← Назад",
                    callback_data=self.callback("history", "page", str(page - 1)),
                )
            )
        if has_next:
            navigation.append(
                InlineKeyboardButton(
                    text="Вперёд →",
                    callback_data=self.callback("history", "page", str(page + 1)),
                )
            )
        if navigation:
            rows.append(navigation)
        rows.extend(
            [
                [InlineKeyboardButton(text=self.texts.new_button, callback_data=self._new)],
                [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _navigation_rows(self) -> list[list[InlineKeyboardButton]]:
        return [
            [InlineKeyboardButton(text=self.texts.new_button, callback_data=self._new)],
            [InlineKeyboardButton(text=self.texts.history_button, callback_data=self._history)],
            [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
        ]

    @property
    def _new(self) -> str:
        return self.callback("new")

    @property
    def _cancel(self) -> str:
        return self.callback("cancel")

    @property
    def _menu(self) -> str:
        return self.callback("menu")

    @property
    def _history(self) -> str:
        return self.callback("history")


@dataclass(frozen=True, slots=True)
class PersonaReadingBundle:
    """The per-persona services a flow needs, resolved once at composition time."""

    use_case: PersonaReadingUseCase
    monetized: MonetizedReadingService
