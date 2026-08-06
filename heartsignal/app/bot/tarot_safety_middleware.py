"""Stop unsafe tarot intake before mystical Telegram handlers run."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.states import TarotStates
from app.bot.tarot_keyboards import tarot_handoff_keyboard
from app.domain.oracle_safety import OracleInputSafetyClassifier
from app.services.oracle_crisis_handoff import OracleCrisisHandoffService

logger = logging.getLogger(__name__)


class _StateContext(Protocol):
    async def get_state(self) -> str | None: ...

    async def get_data(self) -> dict[str, Any]: ...

    async def clear(self) -> None: ...


class TarotSafetyHandoffMiddleware(BaseMiddleware):
    """Intercept unsafe question/context input before persistence or LLM work."""

    def __init__(
        self,
        classifier: OracleInputSafetyClassifier | None = None,
        handoffs: OracleCrisisHandoffService | None = None,
    ) -> None:
        self._classifier = classifier or OracleInputSafetyClassifier()
        self._handoffs = handoffs or OracleCrisisHandoffService()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state = data.get("state")
        if state is None or not self._is_tarot_intake_event(event):
            return await handler(event, data)

        state_context: _StateContext = state
        state_name = await state_context.get_state()
        question, context = await self._input_for_state(event, state_context, state_name)
        if question is None:
            return await handler(event, data)

        safety = self._classifier.classify(question, context)
        if safety.may_reach_persona_prompt:
            return await handler(event, data)

        await state_context.clear()
        locale = event.from_user.language_code if event.from_user is not None else None
        handoff = self._handoffs.build(safety.action, safety.categories, locale=locale)
        logger.info(
            "oracle_crisis_handoff action=%s categories=%s locale=%s",
            safety.action.value,
            ",".join(category.value for category in safety.categories),
            handoff.locale,
        )
        if isinstance(event, CallbackQuery):
            await event.answer()
            if isinstance(event.message, Message):
                await event.message.answer(
                    self._handoffs.render_text(handoff),
                    reply_markup=tarot_handoff_keyboard(),
                )
        elif isinstance(event, Message):
            await event.answer(
                self._handoffs.render_text(handoff),
                reply_markup=tarot_handoff_keyboard(),
            )
        return None

    @staticmethod
    def _is_tarot_intake_event(event: TelegramObject) -> bool:
        if isinstance(event, Message):
            return event.text is not None
        return isinstance(event, CallbackQuery) and event.data == "tarot:context:skip"

    @staticmethod
    async def _input_for_state(
        event: TelegramObject,
        state: _StateContext,
        state_name: str | None,
    ) -> tuple[str | None, str | None]:
        if state_name == TarotStates.waiting_for_question.state and isinstance(event, Message):
            return event.text, None
        if state_name != TarotStates.waiting_for_context.state:
            return None, None

        stored = await state.get_data()
        question = stored.get("tarot_question")
        if not isinstance(question, str):
            return None, None
        if isinstance(event, Message):
            return question, event.text
        if isinstance(event, CallbackQuery) and event.data == "tarot:context:skip":
            return question, None
        return None, None
