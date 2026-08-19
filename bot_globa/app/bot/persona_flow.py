"""Declarative description of one persona's Telegram reading flow.

A flow owns everything that differs between personas — callback namespace, FSM states,
copy and keyboards — so `app.bot.persona_handlers` can stay persona-neutral.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from aiogram.fsm.state import State
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.reading_renderer import ReadingCopy
from app.bot.safety_intake import SafetyIntake, state_name
from app.services.monetized_reading import MonetizedReadingService
from app.services.oracle_memory import OracleMemoryService
from app.services.persona_reading import PersonaReadingUseCase

MENU_BUTTON = "← В главное меню"
CANCEL_BUTTON = "Отмена"
BACK_TO_TOPICS_BUTTON = "← Назад к темам"
BACK_TO_READINGS_BUTTON = "← К моим разборам"
SKIP_CONTEXT_BUTTON = "Без контекста"
RETRY_BUTTON = "Попробовать ещё раз"
FOLLOWUP_BUTTON = "💬 Продолжить — Numa помнит этот сеанс"
FOLLOWUP_NAMESPACE = "rfu"
FEEDBACK_NAMESPACE = "rfb"

NOT_ONBOARDED = "Сначала отправьте /start и примите условия использования."
INVALID_TEXT = "Нужно обычное текстовое сообщение допустимой длины."
QUESTION_PROMPT = (
    "Расскажите ситуацию одним сообщением. Не нужно подбирать правильный формат: напишите, "
    "что происходит и что больше всего хотите понять — Numa сама соберёт подходящий разбор."
)
QUESTION_EXAMPLE = "Например: {example}"
UNLOCKING = "Проверяю доступ и открываю глубокий разбор…"

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


@dataclass(frozen=True, slots=True)
class ReadingFlow:
    """The transport contract every reading persona shares: namespace, states, keyboards.

    The astrologer reuses this without being a `PersonaFlow`: it has extra birth-profile
    intake states and renders calculated facts instead of a structured reading result.
    """

    persona_code: str
    namespace: str
    states: type[ReadingStates]
    topic_labels: Mapping[str, str]
    topic_examples: Mapping[str, str]
    texts: PersonaFlowTexts

    def safety_intake(self) -> SafetyIntake:
        """Register this flow with the crisis middleware."""
        return SafetyIntake(
            persona_code=self.persona_code,
            question_state=state_name(self.states.waiting_for_question),
            context_state=state_name(self.states.waiting_for_context),
            skip_context_callback=self.callback("context", "skip"),
            handoff_keyboard=self.handoff_keyboard,
        )

    def callback(self, *parts: str) -> str:
        """Build a callback payload; Telegram allows 64 bytes, so namespaces stay short."""
        return ":".join((self.namespace, *parts))

    def topics_keyboard(self) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(text=label, callback_data=self.callback("topic", code))]
            for code, label in self.topic_labels.items()
        ]
        rows.append([InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def question_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Показать пример",
                        callback_data=self.callback("example"),
                    )
                ],
                [InlineKeyboardButton(text=BACK_TO_TOPICS_BUTTON, callback_data=self._new)],
                [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
            ]
        )

    def context_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=SKIP_CONTEXT_BUTTON,
                        callback_data=self.callback("context", "skip"),
                    )
                ],
                [InlineKeyboardButton(text=BACK_TO_TOPICS_BUTTON, callback_data=self._new)],
                [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
            ]
        )

    def handoff_keyboard(self) -> InlineKeyboardMarkup:
        """Do not invite another mystical action from an active safety handoff."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
            ]
        )

    def full_result_keyboard(
        self,
        reading_id: UUID,
    ) -> InlineKeyboardMarkup:
        """A paid result is the entry point back into its 24-hour session."""
        rows = [
            [
                InlineKeyboardButton(
                    text=FOLLOWUP_BUTTON,
                    callback_data=f"{FOLLOWUP_NAMESPACE}:ask:{reading_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Попало",
                    callback_data=f"{FEEDBACK_NAMESPACE}:hit:{reading_id}",
                ),
                InlineKeyboardButton(
                    text="Не откликнулось",
                    callback_data=f"{FEEDBACK_NAMESPACE}:miss:{reading_id}",
                ),
            ],
            [InlineKeyboardButton(text=BACK_TO_READINGS_BUTTON, callback_data="menu:readings")],
            [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def result_keyboard(
        self,
        reading_id: UUID | None = None,
        price: str | int | None = None,
    ) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if reading_id is not None and price is not None:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"✨ Открыть глубокий разбор — {price}",
                        callback_data=self.callback("unlock", str(reading_id)),
                    )
                ]
            )
            rows.append([InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)])
        else:
            rows.append([InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def retry_keyboard(self, reading_id: UUID) -> InlineKeyboardMarkup:
        rows = [
            [
                InlineKeyboardButton(
                    text=RETRY_BUTTON,
                    callback_data=self.callback("retry", str(reading_id)),
                )
            ],
            [InlineKeyboardButton(text=BACK_TO_READINGS_BUTTON, callback_data="menu:readings")],
            [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
        ]
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
                [InlineKeyboardButton(text=BACK_TO_READINGS_BUTTON, callback_data="menu:readings")],
                [InlineKeyboardButton(text=MENU_BUTTON, callback_data=self._menu)],
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

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
class PersonaFlow(ReadingFlow):
    """A reading flow whose result is a `reading-result-v1` structure."""

    copy: ReadingCopy


# The spread is drawn deterministically before the model is called, so it can be revealed
# one symbol at a time while the interpretation is written. Two seconds per symbol keeps
# the reveal inside the generation it accompanies and inside the edit rate Telegram
# tolerates for a message that at-least-once delivery may render twice.
SYMBOL_REVEAL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class PersonaReadingBundle:
    """The per-persona services a flow needs, resolved once at composition time."""

    use_case: PersonaReadingUseCase
    monetized: MonetizedReadingService
    full_price_label: str
    memory: OracleMemoryService
    reveal_seconds: float = SYMBOL_REVEAL_SECONDS
