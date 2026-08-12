"""Stop unsafe reading intake before any persona handler runs.

Classification happens here, ahead of persistence and the LLM, so an unsafe question
never reaches a prompt and never becomes stored ciphertext. Every intake surface — the
three shared persona flows and the astrologer — registers a `SafetyIntake` so none of
them can be added without safety coverage.
"""

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.horoscope_flow import horoscope_safety_intake
from app.bot.persona_flows import MVP_READING_FLOWS
from app.bot.reading_followup_handlers import followup_safety_intake
from app.bot.safety_intake import SafetyIntake
from app.bot.scene_media import Scene, answer_scene
from app.domain.oracle_safety import OracleInputSafetyClassifier, OracleRiskCategory
from app.services.oracle_crisis_handoff import OracleCrisisHandoffService

logger = logging.getLogger(__name__)


class _StateContext(Protocol):
    async def get_state(self) -> str | None: ...

    async def get_data(self) -> dict[str, Any]: ...

    async def clear(self) -> None: ...


def mvp_safety_intakes() -> tuple[SafetyIntake, ...]:
    """Every intake surface that may carry a user-authored question."""
    return (
        *(flow.safety_intake() for flow in MVP_READING_FLOWS),
        horoscope_safety_intake(),
        followup_safety_intake(),
    )


class ReadingSafetyHandoffMiddleware(BaseMiddleware):
    """Intercept unsafe question/context input for every reading intake."""

    def __init__(
        self,
        intakes: Iterable[SafetyIntake] | None = None,
        classifier: OracleInputSafetyClassifier | None = None,
        handoffs: OracleCrisisHandoffService | None = None,
    ) -> None:
        resolved = tuple(intakes) if intakes is not None else mvp_safety_intakes()
        self._classifier = classifier or OracleInputSafetyClassifier()
        self._handoffs = handoffs or OracleCrisisHandoffService()
        self._by_question_state = {intake.question_state: intake for intake in resolved}
        self._by_context_state = {
            intake.context_state: intake for intake in resolved if intake.context_state is not None
        }
        self._skip_context_callbacks = {
            intake.skip_context_callback
            for intake in resolved
            if intake.skip_context_callback is not None
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
        intake = self._intake_for(state_name)
        if intake is None:
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
            intake.persona_code,
            safety.action.value,
            ",".join(category.value for category in safety.categories),
            handoff.locale,
        )
        text = self._handoffs.render_text(handoff)
        markup = intake.handoff_keyboard()
        scene = _handoff_scene(safety.categories)
        if isinstance(event, CallbackQuery):
            await event.answer()
            if isinstance(event.message, Message):
                await answer_scene(event.message, scene, text, reply_markup=markup)
        elif isinstance(event, Message):
            await answer_scene(event, scene, text, reply_markup=markup)
        return None

    def _intake_for(self, state_name: str | None) -> SafetyIntake | None:
        if state_name is None:
            return None
        return self._by_question_state.get(state_name) or self._by_context_state.get(state_name)

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


def _handoff_scene(categories: tuple[OracleRiskCategory, ...]) -> Scene:
    if OracleRiskCategory.SELF_HARM in categories:
        return Scene.CRISIS
    if OracleRiskCategory.VIOLENCE_OR_STALKING in categories:
        return Scene.VIOLENCE
    return Scene.HIGH_STAKES
