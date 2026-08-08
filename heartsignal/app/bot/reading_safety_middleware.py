"""Stop unsafe reading intake before any persona handler runs.

Classification happens here, ahead of persistence and the LLM, so an unsafe question
never reaches a prompt and never becomes stored ciphertext.
"""

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.persona_flow import PersonaFlow
from app.bot.persona_flows import MVP_READING_FLOWS
from app.domain.oracle_safety import OracleInputSafetyClassifier
from app.services.oracle_crisis_handoff import OracleCrisisHandoffService

logger = logging.getLogger(__name__)


class _StateContext(Protocol):
    async def get_state(self) -> str | None: ...

    async def get_data(self) -> dict[str, Any]: ...

    async def clear(self) -> None: ...


class ReadingSafetyHandoffMiddleware(BaseMiddleware):
    """Intercept unsafe question/context input for every persona reading flow."""

    def __init__(
        self,
        flows: Iterable[PersonaFlow] = MVP_READING_FLOWS,
        classifier: OracleInputSafetyClassifier | None = None,
        handoffs: OracleCrisisHandoffService | None = None,
    ) -> None:
        self._classifier = classifier or OracleInputSafetyClassifier()
        self._handoffs = handoffs or OracleCrisisHandoffService()
        self._by_question_state = {flow.states.waiting_for_question.state: flow for flow in flows}
        self._by_context_state = {flow.states.waiting_for_context.state: flow for flow in flows}
        self._skip_context_callbacks = {
            flow.callback("context", "skip") for flow in self._by_context_state.values()
        }

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state = data.get("state")
        if state is None or not self._is_intake_event(event):
            return await handler(event, data)

        state_context: _StateContext = state
        state_name = await state_context.get_state()
        flow = self._by_question_state.get(state_name) or self._by_context_state.get(state_name)
        if flow is None:
            return await handler(event, data)

        question, context = await self._input_for_state(event, state_context, state_name)
        if question is None:
            return await handler(event, data)

        safety = self._classifier.classify(question, context)
        if safety.may_reach_persona_prompt:
            return await handler(event, data)

        await state_context.clear()
        handoff = self._handoffs.build(
            safety.action,
            safety.categories,
            locale=_locale(event),
        )
        logger.info(
            "oracle_crisis_handoff persona=%s action=%s categories=%s locale=%s",
            flow.persona_code,
            safety.action.value,
            ",".join(category.value for category in safety.categories),
            handoff.locale,
        )
        text = self._handoffs.render_text(handoff)
        markup = flow.handoff_keyboard()
        if isinstance(event, CallbackQuery):
            await event.answer()
            if isinstance(event.message, Message):
                await event.message.answer(text, reply_markup=markup)
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=markup)
        return None

    def _is_intake_event(self, event: TelegramObject) -> bool:
        if isinstance(event, Message):
            return event.text is not None
        return isinstance(event, CallbackQuery) and event.data in self._skip_context_callbacks

    async def _input_for_state(
        self,
        event: TelegramObject,
        state: _StateContext,
        state_name: str | None,
    ) -> tuple[str | None, str | None]:
        if state_name in self._by_question_state and isinstance(event, Message):
            return event.text, None
        if state_name not in self._by_context_state:
            return None, None

        stored = await state.get_data()
        question = stored.get("question")
        if not isinstance(question, str):
            return None, None
        if isinstance(event, Message):
            return question, event.text
        if isinstance(event, CallbackQuery) and event.data in self._skip_context_callbacks:
            return question, None
        return None, None


def _locale(event: TelegramObject) -> str | None:
    if isinstance(event, CallbackQuery):
        return event.from_user.language_code
    if isinstance(event, Message) and event.from_user is not None:
        return event.from_user.language_code
    return None
