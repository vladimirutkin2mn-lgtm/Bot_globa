"""One persona-neutral router for the follow-up included with a paid reading.

The entitlement is addressed by `reading_id`, so this router is registered once rather
than per persona: which use case produced the reading does not change how a follow-up
is asked, answered or fenced.
"""

import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards import main_menu_keyboard
from app.bot.persona_flow import FOLLOWUP_NAMESPACE, MENU_BUTTON, NOT_ONBOARDED
from app.bot.safety_intake import SafetyIntake, state_name
from app.bot.scene_media import Scene, answer_scene
from app.bot.states import ReadingFollowUpStates
from app.services.onboarding import OnboardingService
from app.services.reading_followup import (
    ReadingFollowUpResultView,
    ReadingFollowUpService,
    ReadingFollowUpStatus,
)

logger = logging.getLogger(__name__)

QUESTION_LIMIT = 1000

PROMPT = (
    "Задайте один вопрос по этому разбору. Он уже включён в покупку: новый расклад "
    "не создаётся, списаний не будет."
)
NOT_ELIGIBLE = "Уточняющий вопрос доступен только для оплаченного полного разбора."
ALREADY_USED = "Уточняющий вопрос по этому разбору уже задан. Вот сохранённый ответ:"
PROCESSING = "Вопрос уже обрабатывается. Откройте разбор немного позже."
WORKING = "Собираю ответ по разбору…"
INVALID = "Нужен обычный текстовый вопрос до 1000 символов."
FAILED = "Не удалось подготовить ответ. Попытка не потрачена — можно спросить ещё раз."
CORRUPTED = "Сохранённый ответ повреждён и не может быть показан."
UNAVAILABLE = "Разбор недоступен. Откройте его из истории."
ANSWER_TITLE = "Уточняющий вопрос"
LIMITATIONS_TITLE = "Границы ответа:"
RETRY_BUTTON = "Спросить ещё раз"


def followup_safety_intake() -> SafetyIntake:
    """A follow-up question is user-authored text and must be classified like any other."""
    return SafetyIntake(
        persona_code="reading_followup",
        question_state=state_name(ReadingFollowUpStates.waiting_for_question),
        handoff_keyboard=_handoff_keyboard,
    )


def create_reading_followup_router() -> Router:
    handlers = ReadingFollowUpHandlers()
    router = Router(name=FOLLOWUP_NAMESPACE)
    router.message.register(handlers.receive_question, ReadingFollowUpStates.waiting_for_question)
    router.callback_query.register(
        handlers.start,
        F.data.startswith(f"{FOLLOWUP_NAMESPACE}:ask:"),
    )
    router.callback_query.register(
        handlers.cancel,
        F.data == f"{FOLLOWUP_NAMESPACE}:cancel",
    )
    return router


class ReadingFollowUpHandlers:
    """Ask once, answer once; a technical failure returns the entitlement."""

    async def start(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        reading_followups: ReadingFollowUpService,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        reading_id = _reading_id(callback.data)
        if reading_id is None:
            await callback.message.answer(UNAVAILABLE, reply_markup=main_menu_keyboard())
            return
        current = await reading_followups.inspect(reading_id, user.id)
        if current.status is ReadingFollowUpStatus.COMPLETED:
            await _send(
                callback.message,
                current,
                prefix=ALREADY_USED,
                scene=Scene.FOLLOW_UP_ALREADY_USED,
            )
            return
        if current.status is ReadingFollowUpStatus.NOT_ELIGIBLE:
            await answer_scene(
                callback.message,
                Scene.FOLLOW_UP_ALREADY_USED,
                NOT_ELIGIBLE,
                reply_markup=main_menu_keyboard(),
            )
            return
        if current.status is ReadingFollowUpStatus.PROCESSING:
            await answer_scene(
                callback.message,
                Scene.FOLLOW_UP_GENERATING,
                PROCESSING,
                reply_markup=main_menu_keyboard(),
            )
            return
        if current.status is ReadingFollowUpStatus.CORRUPTED_HISTORY:
            await answer_scene(
                callback.message,
                Scene.FOLLOW_UP_FAILED,
                CORRUPTED,
                reply_markup=main_menu_keyboard(),
            )
            return
        await state.set_state(ReadingFollowUpStates.waiting_for_question)
        await state.update_data(reading_id=str(reading_id))
        await answer_scene(
            callback.message,
            Scene.FOLLOW_UP_QUESTION,
            PROMPT,
            reply_markup=_cancel_keyboard(),
        )

    async def cancel(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if isinstance(callback.message, Message):
            await callback.message.answer(
                "Уточняющий вопрос отменён.", reply_markup=main_menu_keyboard()
            )

    async def receive_question(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
        reading_followups: ReadingFollowUpService,
    ) -> None:
        if message.from_user is None:
            return
        question = _bounded_text(message)
        if question is None:
            await answer_scene(
                message,
                Scene.FOLLOW_UP_QUESTION,
                INVALID,
                reply_markup=_cancel_keyboard(),
            )
            return
        data = await state.get_data()
        reading_id = _stored_reading_id(data.get("reading_id"))
        user = await onboarding.current_user(message.from_user.id)
        if reading_id is None or user is None:
            await state.clear()
            await message.answer(UNAVAILABLE, reply_markup=main_menu_keyboard())
            return
        await state.clear()
        await answer_scene(message, Scene.FOLLOW_UP_GENERATING, WORKING)
        outcome = await reading_followups.ask(reading_id, user.id, question)
        if outcome.status is ReadingFollowUpStatus.COMPLETED:
            await _send(message, outcome)
            return
        if outcome.status is ReadingFollowUpStatus.INVALID_QUESTION:
            await answer_scene(message, Scene.FOLLOW_UP_QUESTION, INVALID)
            return
        if outcome.status is ReadingFollowUpStatus.PROCESSING:
            await answer_scene(
                message,
                Scene.FOLLOW_UP_GENERATING,
                PROCESSING,
                reply_markup=main_menu_keyboard(),
            )
            return
        if outcome.status is ReadingFollowUpStatus.NOT_ELIGIBLE:
            await answer_scene(
                message,
                Scene.FOLLOW_UP_ALREADY_USED,
                NOT_ELIGIBLE,
                reply_markup=main_menu_keyboard(),
            )
            return
        await answer_scene(
            message,
            Scene.FOLLOW_UP_FAILED,
            FAILED,
            reply_markup=_retry_keyboard(reading_id),
        )
        logger.info(
            "reading_followup_not_delivered reading_id=%s status=%s failure_code=%s",
            reading_id,
            outcome.status.value,
            outcome.failure_code,
        )


async def _send(
    message: Message,
    outcome: ReadingFollowUpResultView,
    *,
    prefix: str | None = None,
    scene: Scene = Scene.FOLLOW_UP_RESULT,
) -> None:
    view = outcome.view
    if view is None:
        await message.answer(CORRUPTED, reply_markup=main_menu_keyboard())
        return
    sections = [f"{ANSWER_TITLE}: {view.question}", view.answer]
    if view.limitations:
        sections.append(LIMITATIONS_TITLE + "\n" + "\n".join(f"• {v}" for v in view.limitations))
    body = "\n\n".join(sections)
    await answer_scene(
        message,
        scene,
        body if prefix is None else f"{prefix}\n\n{body}",
        reply_markup=main_menu_keyboard(),
    )


def _handoff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=MENU_BUTTON, callback_data="report:menu")]]
    )


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"{FOLLOWUP_NAMESPACE}:cancel",
                )
            ]
        ]
    )


def _retry_keyboard(reading_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=RETRY_BUTTON,
                    callback_data=f"{FOLLOWUP_NAMESPACE}:ask:{reading_id}",
                )
            ],
            [InlineKeyboardButton(text=MENU_BUTTON, callback_data="report:menu")],
        ]
    )


def _reading_id(data: str | None) -> UUID | None:
    return _stored_reading_id((data or "").removeprefix(f"{FOLLOWUP_NAMESPACE}:ask:"))


def _stored_reading_id(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _bounded_text(message: Message) -> str | None:
    if message.text is None:
        return None
    value = message.text.strip()
    if not value or len(value) > QUESTION_LIMIT:
        return None
    return value
