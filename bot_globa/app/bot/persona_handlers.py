"""Persona-neutral Telegram FSM for structured oracle readings.

`create_persona_router` builds one isolated router per persona from a `PersonaFlow`;
nothing in this module knows about tarot, love or reflection specifically.
"""

import logging
from collections.abc import Mapping
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot.keyboards import main_menu_keyboard
from app.bot.persona_flow import (
    CONTEXT_LIMIT,
    CONTEXT_PROMPT,
    INSUFFICIENT,
    INVALID_TEXT,
    MENU_BUTTON,
    NOT_ONBOARDED,
    QUESTION_LIMIT,
    QUESTION_PROMPT,
    UNLOCKING,
    PersonaFlow,
    PersonaReadingBundle,
)
from app.bot.reading_renderer import render_full, render_preview
from app.bot.scene_media import Scene, answer_scene
from app.services.monetized_reading import MonetizedReadingStatus
from app.services.onboarding import OnboardingService
from app.services.persona_reading import PersonaPreviewOutcome, PersonaPreviewRequest
from app.services.preview_entitlement import ReadingPreviewVisibility
from app.services.reading_generation import ReadingGenerationStatus
from app.services.reading_history import ReadingHistoryService

logger = logging.getLogger(__name__)

TOPIC_UNAVAILABLE = "Эта тема недоступна."

PersonaReadings = Mapping[str, PersonaReadingBundle]


def create_persona_router(flow: PersonaFlow) -> Router:
    """Register the complete reading flow for one persona under its own namespace."""
    handlers = PersonaReadingHandlers(flow)
    router = Router(name=flow.namespace)

    router.message.register(handlers.start_from_command, Command(flow.namespace))
    router.message.register(handlers.receive_question, flow.states.waiting_for_question)
    router.message.register(handlers.receive_context, flow.states.waiting_for_context)
    router.message.register(handlers.already_generating, flow.states.generating)

    callbacks = router.callback_query
    callbacks.register(handlers.start_from_menu, F.data == f"menu:{flow.namespace}")
    callbacks.register(
        handlers.restart,
        F.data.in_({flow.callback("new"), flow.callback("cancel")}),
    )
    callbacks.register(handlers.to_main_menu, F.data == flow.callback("menu"))
    callbacks.register(handlers.show_history, F.data == flow.callback("history"))
    callbacks.register(
        handlers.show_history_page,
        F.data.startswith(flow.callback("history", "page", "")),
    )
    callbacks.register(
        handlers.open_from_history,
        F.data.startswith(flow.callback("history", "open", "")),
    )
    callbacks.register(handlers.select_topic, F.data.startswith(flow.callback("topic", "")))
    callbacks.register(
        handlers.skip_context,
        flow.states.waiting_for_context,
        F.data == flow.callback("context", "skip"),
    )
    callbacks.register(handlers.retry, F.data.startswith(flow.callback("retry", "")))
    callbacks.register(handlers.unlock, F.data.startswith(flow.callback("unlock", "")))
    return router


class PersonaReadingHandlers:
    """Every handler for one persona; the flow supplies namespace, states and copy."""

    def __init__(self, flow: PersonaFlow) -> None:
        self._flow = flow

    # ------------------------------------------------------------------ entry ---

    async def start_from_command(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
    ) -> None:
        if message.from_user is None:
            return
        if await self._onboarded(message.from_user.id, state, message, onboarding):
            await self._show_topics(message, state)

    async def start_from_menu(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if await self._onboarded(callback.from_user.id, state, callback.message, onboarding):
            await self._show_topics(callback.message, state)

    async def restart(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
    ) -> None:
        await self.start_from_menu(callback, state, onboarding)

    async def to_main_menu(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if isinstance(callback.message, Message):
            await answer_scene(
                callback.message,
                Scene.MAIN_MENU,
                MENU_BUTTON,
                reply_markup=main_menu_keyboard(),
            )

    # ------------------------------------------------------------------ intake ---

    async def select_topic(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        topic = (callback.data or "").removeprefix(self._flow.callback("topic", ""))
        if topic not in self._flow.topic_labels:
            await answer_scene(
                callback.message,
                self._entry_scene,
                TOPIC_UNAVAILABLE,
                reply_markup=self._flow.topics_keyboard(),
            )
            return
        await state.update_data(topic=topic)
        await state.set_state(self._flow.states.waiting_for_question)
        await answer_scene(callback.message, Scene.QUESTION, QUESTION_PROMPT)

    async def receive_question(self, message: Message, state: FSMContext) -> None:
        text = _bounded_text(message, maximum=QUESTION_LIMIT)
        if text is None:
            await answer_scene(message, Scene.QUESTION_ERROR, INVALID_TEXT)
            return
        await state.update_data(question=text)
        await state.set_state(self._flow.states.waiting_for_context)
        await answer_scene(
            message,
            Scene.CONTEXT,
            CONTEXT_PROMPT,
            reply_markup=self._flow.context_keyboard(),
        )

    async def receive_context(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
        persona_readings: PersonaReadings,
    ) -> None:
        if message.from_user is None:
            return
        context = _bounded_text(message, maximum=CONTEXT_LIMIT)
        if context is None:
            await answer_scene(
                message,
                Scene.QUESTION_ERROR,
                INVALID_TEXT,
                reply_markup=self._flow.context_keyboard(),
            )
            return
        await self._generate_new(
            message,
            message.from_user.id,
            state,
            onboarding,
            persona_readings,
            context=context,
        )

    async def skip_context(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        persona_readings: PersonaReadings,
    ) -> None:
        await callback.answer()
        if isinstance(callback.message, Message):
            await self._generate_new(
                callback.message,
                callback.from_user.id,
                state,
                onboarding,
                persona_readings,
                context=None,
            )

    async def already_generating(self, message: Message) -> None:
        await answer_scene(
            message,
            Scene.GENERATION_IN_PROGRESS,
            self._flow.texts.already_processing,
        )

    # ----------------------------------------------------------------- history ---

    async def show_history(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        reading_history: ReadingHistoryService,
    ) -> None:
        await callback.answer()
        if isinstance(callback.message, Message):
            await self._show_history(
                callback.message,
                callback.from_user.id,
                state,
                onboarding,
                reading_history,
                page=0,
            )

    async def show_history_page(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        reading_history: ReadingHistoryService,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        prefix = self._flow.callback("history", "page", "")
        try:
            page = int((callback.data or "").removeprefix(prefix))
        except ValueError:
            page = 0
        await self._show_history(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            reading_history,
            page=max(page, 0),
        )

    async def open_from_history(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        persona_readings: PersonaReadings,
    ) -> None:
        await callback.answer()
        await self._regenerate(
            callback,
            state,
            onboarding,
            persona_readings,
            prefix=self._flow.callback("history", "open", ""),
            notice=self._flow.texts.opening,
            notice_scene=Scene.HISTORY_OPEN,
        )

    # ------------------------------------------------------------------ result ---

    async def retry(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        persona_readings: PersonaReadings,
    ) -> None:
        await callback.answer()
        await self._regenerate(
            callback,
            state,
            onboarding,
            persona_readings,
            prefix=self._flow.callback("retry", ""),
            notice=self._flow.texts.processing,
            notice_scene=Scene.GENERATING,
        )

    async def unlock(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        persona_readings: PersonaReadings,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        reading_id = _reading_id(callback.data, self._flow.callback("unlock", ""))
        if reading_id is None:
            await self._answer_unavailable(callback.message)
            return
        bundle = persona_readings[self._flow.persona_code]
        await answer_scene(callback.message, Scene.UNLOCKING, UNLOCKING)
        unlocked = await bundle.monetized.unlock_full(reading_id, user.id)
        if unlocked.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS:
            await answer_scene(
                callback.message,
                Scene.INSUFFICIENT_CREDITS,
                INSUFFICIENT.format(
                    price=bundle.monetized.price_credits,
                    balance=unlocked.balance or 0,
                ),
                reply_markup=self._flow.insufficient_keyboard(reading_id),
            )
            return
        if unlocked.status is MonetizedReadingStatus.FULL_COMPLETED:
            outcome = await bundle.use_case.generate_existing_preview(reading_id, user.id)
            if _is_complete(outcome):
                await self._send_full(callback.message, outcome)
                return
        await answer_scene(
            callback.message,
            Scene.GENERATION_FAILED,
            self._flow.texts.unlock_failed,
            reply_markup=self._flow.result_keyboard(),
        )

    # ----------------------------------------------------------------- internal ---

    async def _onboarded(
        self,
        telegram_user_id: int,
        state: FSMContext,
        message: Message,
        onboarding: OnboardingService,
    ) -> bool:
        if await onboarding.analysis_allowed(telegram_user_id):
            return True
        await state.clear()
        await message.answer(NOT_ONBOARDED)
        return False

    async def _show_topics(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        await answer_scene(
            message,
            self._entry_scene,
            self._flow.texts.welcome,
            reply_markup=self._flow.topics_keyboard(),
        )

    async def _show_history(
        self,
        message: Message,
        telegram_user_id: int,
        state: FSMContext,
        onboarding: OnboardingService,
        history: ReadingHistoryService,
        *,
        page: int,
    ) -> None:
        await state.clear()
        user = await onboarding.current_user(telegram_user_id)
        if user is None:
            await message.answer(NOT_ONBOARDED)
            return
        history_page = await history.list_ready(user.id, self._flow.persona_code, page=page)
        labels = [
            (
                item.reading_id,
                f"{self._flow.topic_labels.get(item.topic, self._flow.texts.history_fallback)}"
                f" · {item.created_at:%d.%m.%Y}",
            )
            for item in history_page.items
        ]
        await answer_scene(
            message,
            Scene.HISTORY if labels else Scene.HISTORY_EMPTY,
            self._flow.texts.history_title if labels else self._flow.texts.history_empty,
            reply_markup=self._flow.history_keyboard(
                labels,
                page=history_page.page,
                has_next=history_page.has_next,
            ),
        )

    async def _generate_new(
        self,
        message: Message,
        telegram_user_id: int,
        state: FSMContext,
        onboarding: OnboardingService,
        persona_readings: PersonaReadings,
        *,
        context: str | None,
    ) -> None:
        user = await onboarding.current_user(telegram_user_id)
        data = await state.get_data()
        topic = data.get("topic")
        question = data.get("question")
        if user is None or not isinstance(topic, str) or not isinstance(question, str):
            await state.clear()
            await self._answer_unavailable(message)
            return
        bundle = persona_readings[self._flow.persona_code]
        await state.set_state(self._flow.states.generating)
        await answer_scene(message, Scene.GENERATING, self._flow.texts.processing)
        try:
            outcome = await bundle.use_case.create_preview(
                user.id,
                PersonaPreviewRequest(topic=topic, question=question, context=context),
            )
        except (LookupError, ValueError):
            await state.clear()
            await self._answer_unavailable(message)
            return
        await self._deliver(message, state, outcome, bundle)

    async def _regenerate(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        persona_readings: PersonaReadings,
        *,
        prefix: str,
        notice: str,
        notice_scene: Scene,
    ) -> None:
        if not isinstance(callback.message, Message):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        reading_id = _reading_id(callback.data, prefix)
        if reading_id is None:
            await self._answer_unavailable(callback.message)
            return
        bundle = persona_readings[self._flow.persona_code]
        await state.set_state(self._flow.states.generating)
        await answer_scene(callback.message, notice_scene, notice)
        outcome = await bundle.use_case.generate_existing_preview(reading_id, user.id)
        await self._deliver(callback.message, state, outcome, bundle)

    async def _deliver(
        self,
        message: Message,
        state: FSMContext,
        outcome: PersonaPreviewOutcome,
        bundle: PersonaReadingBundle,
    ) -> None:
        await state.clear()
        price = bundle.monetized.price_credits
        if _is_complete(outcome):
            if outcome.visibility is ReadingPreviewVisibility.FULL:
                await self._send_full(message, outcome)
                return
            if outcome.visibility is ReadingPreviewVisibility.PREVIEW:
                await _send_chunks(
                    message,
                    render_preview(outcome, self._flow.copy),
                    self._flow.result_keyboard(outcome.reading_id, price),
                    Scene.PREVIEW,
                )
                return
            await answer_scene(
                message,
                Scene.PREVIEW_ALREADY_USED,
                self._flow.texts.locked.format(price=price),
                reply_markup=self._flow.result_keyboard(outcome.reading_id, price),
            )
            return

        status = outcome.generation.status
        if status is ReadingGenerationStatus.ALREADY_PROCESSING:
            await answer_scene(
                message,
                Scene.GENERATION_IN_PROGRESS,
                self._flow.texts.already_processing,
                reply_markup=self._flow.retry_keyboard(outcome.reading_id),
            )
            return
        if status is ReadingGenerationStatus.FAILED:
            await answer_scene(
                message,
                Scene.GENERATION_FAILED,
                self._flow.texts.failed,
                reply_markup=self._flow.retry_keyboard(outcome.reading_id),
            )
            return
        await self._answer_unavailable(message)
        logger.warning(
            "persona_delivery_unavailable persona=%s reading_id=%s status=%s",
            self._flow.persona_code,
            outcome.reading_id,
            status.value,
        )

    async def _send_full(self, message: Message, outcome: PersonaPreviewOutcome) -> None:
        await _send_chunks(
            message,
            render_full(outcome, self._flow.copy),
            self._flow.full_result_keyboard(outcome.reading_id),
            Scene.FULL_READING,
        )

    async def _answer_unavailable(self, message: Message) -> None:
        await answer_scene(
            message,
            Scene.GENERATION_FAILED,
            self._flow.texts.unavailable,
            reply_markup=self._flow.result_keyboard(),
        )

    @property
    def _entry_scene(self) -> Scene:
        return {
            "tarot_reader": Scene.TAROT_ENTRY,
            "love_oracle": Scene.LOVE_ENTRY,
            "mystical_psychologist": Scene.PSYCHOLOGIST_ENTRY,
        }[self._flow.persona_code]


def _is_complete(outcome: PersonaPreviewOutcome) -> bool:
    return (
        outcome.generation.status is ReadingGenerationStatus.COMPLETED
        and outcome.generation.result is not None
    )


async def _send_chunks(
    message: Message,
    chunks: tuple[str, ...],
    markup: InlineKeyboardMarkup,
    scene: Scene,
) -> None:
    """Attach the keyboard only to the final chunk so a reading reads as one message."""
    for index, chunk in enumerate(chunks):
        reply_markup = markup if index == len(chunks) - 1 else None
        if index == 0:
            await answer_scene(message, scene, chunk, reply_markup=reply_markup)
        else:
            await message.answer(chunk, reply_markup=reply_markup)


def _reading_id(data: str | None, prefix: str) -> UUID | None:
    try:
        return UUID((data or "").removeprefix(prefix))
    except ValueError:
        return None


def _bounded_text(message: Message, *, maximum: int) -> str | None:
    if message.text is None:
        return None
    value = message.text.strip()
    if not value or len(value) > maximum:
        return None
    return value
