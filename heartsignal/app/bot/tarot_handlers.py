"""Isolated Telegram FSM for the first tarot preview experience."""

# ruff: noqa: RUF001

import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import main_menu_keyboard
from app.bot.states import TarotStates
from app.bot.tarot_full_renderer import TarotFullRenderer
from app.bot.tarot_keyboards import (
    TAROT_TOPIC_LABELS,
    tarot_context_keyboard,
    tarot_full_result_keyboard,
    tarot_history_keyboard,
    tarot_insufficient_keyboard,
    tarot_result_keyboard,
    tarot_retry_keyboard,
    tarot_topics_keyboard,
)
from app.bot.tarot_renderer import TarotPreviewRenderer
from app.services.monetized_reading import MonetizedReadingService, MonetizedReadingStatus
from app.services.onboarding import OnboardingService
from app.services.reading_generation import ReadingGenerationStatus
from app.services.reading_history import ReadingHistoryService
from app.services.tarot_reading import (
    TarotPreviewOutcome,
    TarotPreviewRequest,
    TarotReadingUseCase,
)

router = Router(name="tarot")
logger = logging.getLogger(__name__)
renderer = TarotPreviewRenderer()
full_renderer = TarotFullRenderer()

WELCOME = (
    "🔮 Таролог\n\nВыберите тему. Карты выбираются приложением и не меняются при повторе. "
    "Результат предназначен для развлечения и рефлексии."
)
QUESTION_PROMPT = (
    "Напишите один конкретный вопрос. Лучше спрашивать о возможных сценариях, своих решениях "
    "и следующем шаге, а не о гарантированном будущем или чужих тайных мыслях."
)
CONTEXT_PROMPT = (
    "Можно добавить короткий контекст ситуации одним сообщением или продолжить без него."
)
PROCESSING = "Расклад зафиксирован. Собираю интерпретацию…"
OPENING = "Открываю сохранённый расклад…"
NOT_ONBOARDED = "Сначала отправьте /start и завершите подтверждение возраста и условий."
INVALID_TEXT = "Нужно обычное текстовое сообщение допустимой длины."
ALREADY_PROCESSING = "Этот расклад уже обрабатывается. Откройте его немного позже."
UNAVAILABLE = "Таролог временно недоступен. Начните новый расклад позже."
FAILED = "Не удалось завершить интерпретацию. Карты сохранены, поэтому попытку можно повторить."
HISTORY_TITLE = "Ваши последние готовые расклады:"
HISTORY_EMPTY = "Готовых раскладов пока нет."
UNLOCKING = "Проверяю баланс и открываю полный расклад…"
INSUFFICIENT = "Для полного расклада нужно {price} кр. Доступный баланс: {balance} кр."
UNLOCK_FAILED = "Не удалось открыть полный расклад. Списание отменено или возвращено."


@router.message(Command("tarot"))
async def start_tarot(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
) -> None:
    if message.from_user is None:
        return
    if not await onboarding.analysis_allowed(message.from_user.id):
        await state.clear()
        await message.answer(NOT_ONBOARDED)
        return
    await _show_topics(message, state)


@router.callback_query(F.data == "menu:tarot")
async def start_tarot_from_menu(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not await onboarding.analysis_allowed(callback.from_user.id):
        await state.clear()
        await callback.message.answer(NOT_ONBOARDED)
        return
    await _show_topics(callback.message, state)


@router.callback_query(F.data.in_({"tarot:new", "tarot:cancel"}))
async def restart_tarot(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not await onboarding.analysis_allowed(callback.from_user.id):
        await state.clear()
        await callback.message.answer(NOT_ONBOARDED)
        return
    await _show_topics(callback.message, state)


@router.callback_query(F.data == "tarot:menu")
async def tarot_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer("Главное меню", reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "tarot:history")
async def tarot_history(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_history: ReadingHistoryService,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show_history(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            tarot_history,
            page=0,
        )


@router.callback_query(F.data.startswith("tarot:history:page:"))
async def tarot_history_page(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_history: ReadingHistoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    try:
        page = int((callback.data or "").removeprefix("tarot:history:page:"))
    except ValueError:
        page = 0
    await _show_history(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        tarot_history,
        page=max(page, 0),
    )


@router.callback_query(F.data.startswith("tarot:history:open:"))
async def open_tarot_history(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await state.clear()
        await callback.message.answer(NOT_ONBOARDED)
        return
    try:
        reading_id = UUID((callback.data or "").removeprefix("tarot:history:open:"))
    except ValueError:
        await callback.message.answer(UNAVAILABLE, reply_markup=tarot_result_keyboard())
        return
    await state.set_state(TarotStates.generating)
    await callback.message.answer(OPENING)
    outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
    await _deliver(callback.message, state, outcome, tarot_monetized)


@router.callback_query(F.data.startswith("tarot:topic:"))
async def select_tarot_topic(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    topic = (callback.data or "").removeprefix("tarot:topic:")
    if topic not in TAROT_TOPIC_LABELS:
        await callback.message.answer("Эта тема недоступна.", reply_markup=tarot_topics_keyboard())
        return
    await state.update_data(tarot_topic=topic)
    await state.set_state(TarotStates.waiting_for_question)
    await callback.message.answer(QUESTION_PROMPT)


@router.message(TarotStates.waiting_for_question)
async def receive_tarot_question(message: Message, state: FSMContext) -> None:
    text = _bounded_text(message, maximum=8000)
    if text is None:
        await message.answer(INVALID_TEXT)
        return
    await state.update_data(tarot_question=text)
    await state.set_state(TarotStates.waiting_for_context)
    await message.answer(CONTEXT_PROMPT, reply_markup=tarot_context_keyboard())


@router.callback_query(
    TarotStates.waiting_for_context,
    F.data == "tarot:context:skip",
)
async def skip_tarot_context(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _generate_new(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            tarot_use_case,
            tarot_monetized,
            context=None,
        )


@router.message(TarotStates.waiting_for_context)
async def receive_tarot_context(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    if message.from_user is None:
        return
    context = _bounded_text(message, maximum=12000)
    if context is None:
        await message.answer(INVALID_TEXT, reply_markup=tarot_context_keyboard())
        return
    await _generate_new(
        message,
        message.from_user.id,
        state,
        onboarding,
        tarot_use_case,
        tarot_monetized,
        context=context,
    )


@router.callback_query(F.data.startswith("tarot:retry:"))
async def retry_tarot(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await state.clear()
        await callback.message.answer(NOT_ONBOARDED)
        return
    try:
        reading_id = UUID((callback.data or "").removeprefix("tarot:retry:"))
    except ValueError:
        await callback.message.answer(UNAVAILABLE, reply_markup=tarot_result_keyboard())
        return
    await state.set_state(TarotStates.generating)
    await callback.message.answer(PROCESSING)
    outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
    await _deliver(callback.message, state, outcome, tarot_monetized)


@router.callback_query(F.data.startswith("tarot:unlock:"))
async def unlock_tarot(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await state.clear()
        await callback.message.answer(NOT_ONBOARDED)
        return
    try:
        reading_id = UUID((callback.data or "").removeprefix("tarot:unlock:"))
    except ValueError:
        await callback.message.answer(UNAVAILABLE, reply_markup=tarot_result_keyboard())
        return
    await callback.message.answer(UNLOCKING)
    unlocked = await tarot_monetized.unlock_full(reading_id, user.id)
    if unlocked.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS:
        await callback.message.answer(
            INSUFFICIENT.format(
                price=tarot_monetized.price_credits,
                balance=unlocked.balance or 0,
            ),
            reply_markup=tarot_insufficient_keyboard(reading_id),
        )
        return
    if unlocked.status is MonetizedReadingStatus.FULL_COMPLETED:
        outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
        if (
            outcome.generation.status is ReadingGenerationStatus.COMPLETED
            and outcome.generation.result is not None
        ):
            rendered = full_renderer.render(outcome)
            for index, chunk in enumerate(rendered.chunks):
                markup = (
                    tarot_full_result_keyboard()
                    if index == len(rendered.chunks) - 1
                    else None
                )
                await callback.message.answer(chunk, reply_markup=markup)
            return
    await callback.message.answer(UNLOCK_FAILED, reply_markup=tarot_result_keyboard())


@router.message(TarotStates.generating)
async def tarot_is_generating(message: Message) -> None:
    await message.answer(ALREADY_PROCESSING)


async def _show_topics(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=tarot_topics_keyboard())


async def _show_history(
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
    history_page = await history.list_ready(
        user.id,
        TarotReadingUseCase.persona_code,
        page=page,
    )
    labels = [
        (
            item.reading_id,
            f"{TAROT_TOPIC_LABELS.get(item.topic, 'Расклад')} · {item.created_at:%d.%m.%Y}",
        )
        for item in history_page.items
    ]
    text = HISTORY_TITLE if labels else HISTORY_EMPTY
    await message.answer(
        text,
        reply_markup=tarot_history_keyboard(
            labels,
            page=history_page.page,
            has_next=history_page.has_next,
        ),
    )


async def _generate_new(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
    *,
    context: str | None,
) -> None:
    user = await onboarding.current_user(telegram_user_id)
    data = await state.get_data()
    topic = data.get("tarot_topic")
    question = data.get("tarot_question")
    if user is None or not isinstance(topic, str) or not isinstance(question, str):
        await state.clear()
        await message.answer(UNAVAILABLE, reply_markup=tarot_result_keyboard())
        return
    await state.set_state(TarotStates.generating)
    await message.answer(PROCESSING)
    try:
        outcome = await tarot_use_case.create_preview(
            user.id,
            TarotPreviewRequest(topic=topic, question=question, context=context),
        )
    except (LookupError, ValueError):
        await state.clear()
        await message.answer(UNAVAILABLE, reply_markup=tarot_result_keyboard())
        return
    await _deliver(message, state, outcome, tarot_monetized)


async def _deliver(
    message: Message,
    state: FSMContext,
    outcome: TarotPreviewOutcome,
    monetized: MonetizedReadingService,
) -> None:
    await state.clear()
    status = outcome.generation.status
    if status is ReadingGenerationStatus.COMPLETED and outcome.generation.result is not None:
        rendered = renderer.render(outcome)
        for index, chunk in enumerate(rendered.chunks):
            markup = (
                tarot_result_keyboard(outcome.reading_id, monetized.price_credits)
                if index == len(rendered.chunks) - 1
                else None
            )
            await message.answer(chunk, reply_markup=markup)
        return
    if status is ReadingGenerationStatus.ALREADY_PROCESSING:
        await message.answer(
            ALREADY_PROCESSING, reply_markup=tarot_retry_keyboard(outcome.reading_id)
        )
        return
    if status is ReadingGenerationStatus.FAILED:
        await message.answer(FAILED, reply_markup=tarot_retry_keyboard(outcome.reading_id))
        return
    await message.answer(UNAVAILABLE, reply_markup=tarot_result_keyboard())
    logger.warning(
        "tarot_delivery_unavailable reading_id=%s status=%s",
        outcome.reading_id,
        status.value,
    )


def _bounded_text(message: Message, *, maximum: int) -> str | None:
    if message.text is None:
        return None
    value = message.text.strip()
    if not value or len(value) > maximum:
        return None
    return value
