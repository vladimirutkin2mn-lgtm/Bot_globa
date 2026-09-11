"""Telegram UI for manually grouping saved readings into user-owned stories."""

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import texts
from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.bot.reading_story_keyboards import (
    StoryReadingButton,
    stories_hub_keyboard,
    story_add_readings_keyboard,
    story_all_readings_keyboard,
    story_delete_confirmation_keyboard,
    story_detail_keyboard,
    story_title_cancel_keyboard,
)
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import ReadingStoryStates
from app.domain.reading_history import ReadingHistoryChoice
from app.services.onboarding import OnboardingService
from app.services.reading_history import ReadingHistoryService
from app.services.reading_story import (
    ReadingStoryNotFoundError,
    ReadingStoryReadingError,
    ReadingStoryService,
    ReadingStoryTitleError,
)

router = Router(name="reading-stories")

_PAGE_SIZE = 6
_TITLE_MODE_KEY = "reading_story_title_mode"
_TITLE_STORY_KEY = "reading_story_title_id"
_ADD_STORY_KEY = "reading_story_add_id"
_NOT_ONBOARDED = "Сначала отправьте /start."
_STALE = "Эта история уже недоступна. Откройте «Мои истории» заново."


@dataclass(frozen=True, slots=True)
class _FlowMeta:
    namespace: str
    emoji: str
    topic_labels: Mapping[str, str]
    fallback: str


_FLOW_META = {
    TAROT_FLOW.persona_code: _FlowMeta(
        TAROT_FLOW.namespace,
        "🔮",
        TAROT_FLOW.topic_labels,
        TAROT_FLOW.texts.history_fallback,
    ),
    LOVE_ORACLE_FLOW.persona_code: _FlowMeta(
        LOVE_ORACLE_FLOW.namespace,
        "💞",
        LOVE_ORACLE_FLOW.topic_labels,
        LOVE_ORACLE_FLOW.texts.history_fallback,
    ),
    MYSTICAL_PSYCHOLOGIST_FLOW.persona_code: _FlowMeta(
        MYSTICAL_PSYCHOLOGIST_FLOW.namespace,
        "🌙",
        MYSTICAL_PSYCHOLOGIST_FLOW.topic_labels,
        MYSTICAL_PSYCHOLOGIST_FLOW.texts.history_fallback,
    ),
    HOROSCOPE_FLOW.persona_code: _FlowMeta(
        HOROSCOPE_FLOW.namespace,
        "🪐",
        HOROSCOPE_FLOW.topic_labels,
        HOROSCOPE_FLOW.texts.history_fallback,
    ),
}


@router.callback_query(F.data == "menu:readings")
async def stories_home(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show_hub(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            reading_stories,
        )


@router.callback_query(F.data == "stories:all")
async def all_readings(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.HISTORY,
            texts.READINGS_MENU,
            reply_markup=story_all_readings_keyboard(),
            state=state,
        )


@router.callback_query(F.data == "stories:create")
async def begin_story_create(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if await onboarding.current_user(callback.from_user.id) is None:
        await callback.message.answer(_NOT_ONBOARDED)
        return
    await state.clear()
    await state.update_data({_TITLE_MODE_KEY: "create"})
    await state.set_state(ReadingStoryStates.waiting_for_title)
    await show_screen(
        callback.message,
        Scene.HISTORY,
        "Как назвать историю?\n\nНапример: «Новая работа», «Отношения» или «Переезд». "
        "Название увидите только вы.",
        reply_markup=story_title_cancel_keyboard(),
        state=state,
    )


@router.callback_query(F.data.startswith("stories:rename:"))
async def begin_story_rename(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    story_id = _parse_uuid(callback.data, "stories:rename:")
    user = await onboarding.current_user(callback.from_user.id)
    if story_id is None or user is None:
        await callback.message.answer(_STALE)
        return
    try:
        story = await reading_stories.get(user.id, story_id)
    except ReadingStoryNotFoundError:
        await callback.message.answer(_STALE)
        return
    await state.clear()
    await state.update_data({_TITLE_MODE_KEY: "rename", _TITLE_STORY_KEY: str(story.id)})
    await state.set_state(ReadingStoryStates.waiting_for_title)
    await show_screen(
        callback.message,
        Scene.HISTORY,
        f"Новое название для «{escape(story.title)}»\n\nОтправьте его одним сообщением.",
        reply_markup=story_title_cancel_keyboard(story.id),
        state=state,
    )


@router.message(ReadingStoryStates.waiting_for_title)
async def save_story_title(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
    reading_history: ReadingHistoryService,
) -> None:
    if message.from_user is None:
        return
    user = await onboarding.current_user(message.from_user.id)
    if user is None:
        await state.clear()
        await message.answer(_NOT_ONBOARDED)
        return
    data = await state.get_data()
    mode = data.get(_TITLE_MODE_KEY)
    story_id = _uuid_value(data.get(_TITLE_STORY_KEY))
    title = message.text or ""
    try:
        if mode == "create":
            story = await reading_stories.create(user.id, title)
        elif mode == "rename" and story_id is not None:
            story = await reading_stories.rename(user.id, story_id, title)
        else:
            await state.clear()
            await _show_hub(message, message.from_user.id, state, onboarding, reading_stories)
            return
    except ReadingStoryTitleError:
        await show_screen(
            message,
            Scene.HISTORY,
            "Название должно быть непустым и не длиннее 120 символов. Попробуйте ещё раз.",
            reply_markup=story_title_cancel_keyboard(story_id),
            state=state,
        )
        return
    except ReadingStoryNotFoundError:
        await state.clear()
        await message.answer(_STALE)
        await _show_hub(message, message.from_user.id, state, onboarding, reading_stories)
        return
    await state.clear()
    await _show_story(
        message,
        user.id,
        story.id,
        0,
        state,
        reading_stories,
        reading_history,
    )


@router.callback_query(F.data.startswith("stories:open:"))
async def open_story(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
    reading_history: ReadingHistoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parsed = _parse_story_page(callback.data, "stories:open:")
    user = await onboarding.current_user(callback.from_user.id)
    if parsed is None or user is None:
        await callback.message.answer(_STALE)
        return
    story_id, page = parsed
    try:
        await state.clear()
        await _show_story(
            callback.message,
            user.id,
            story_id,
            page,
            state,
            reading_stories,
            reading_history,
        )
    except ReadingStoryNotFoundError:
        await callback.message.answer(_STALE)
        await _show_hub(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            reading_stories,
        )


@router.callback_query(F.data.startswith("stories:add:"))
async def add_reading_screen(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
    reading_history: ReadingHistoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parsed = _parse_story_page(callback.data, "stories:add:")
    user = await onboarding.current_user(callback.from_user.id)
    if parsed is None or user is None:
        await callback.message.answer(_STALE)
        return
    story_id, page = parsed
    try:
        story = await reading_stories.get(user.id, story_id)
    except ReadingStoryNotFoundError:
        await callback.message.answer(_STALE)
        return
    choices = await reading_history.list_ready_all(user.id, page=page, page_size=_PAGE_SIZE)
    buttons = tuple(_reading_button(item) for item in choices.items)
    await state.clear()
    await state.update_data({_ADD_STORY_KEY: str(story.id)})
    await show_screen(
        callback.message,
        Scene.HISTORY,
        f"Добавить разбор в «{escape(story.title)}»\n\n"
        "Выберите готовый разбор. Если он уже связан с другой историей, связь будет "
        "перенесена сюда; сам разбор не изменится.",
        reply_markup=story_add_readings_keyboard(
            story.id,
            buttons,
            page=choices.page,
            has_next=choices.has_next,
        ),
        state=state,
    )


@router.callback_query(F.data.startswith("stories:pick:"))
async def pick_reading(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
    reading_history: ReadingHistoryService,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    reading_id = _parse_uuid(callback.data, "stories:pick:")
    data = await state.get_data()
    story_id = _uuid_value(data.get(_ADD_STORY_KEY))
    user = await onboarding.current_user(callback.from_user.id)
    if reading_id is None or story_id is None or user is None:
        await callback.answer(
            "Откройте историю и выберите «Добавить разбор» ещё раз.", show_alert=True
        )
        return
    try:
        await reading_stories.link_reading(user.id, story_id, reading_id)
    except (ReadingStoryNotFoundError, ReadingStoryReadingError):
        await callback.answer("Разбор или история уже недоступны.", show_alert=True)
        return
    await callback.answer("Разбор добавлен")
    await state.clear()
    await _show_story(
        callback.message,
        user.id,
        story_id,
        0,
        state,
        reading_stories,
        reading_history,
    )


@router.callback_query(F.data.startswith("stories:unlink:"))
async def unlink_reading(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
    reading_history: ReadingHistoryService,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    reading_id = _parse_uuid(callback.data, "stories:unlink:")
    user = await onboarding.current_user(callback.from_user.id)
    if reading_id is None or user is None:
        await callback.answer("Связь уже недоступна.", show_alert=True)
        return
    story_id = await reading_stories.unlink_owned_reading(user.id, reading_id)
    if story_id is None:
        await callback.answer("Связь уже удалена.")
        return
    await callback.answer("Разбор убран из истории")
    await state.clear()
    await _show_story(
        callback.message,
        user.id,
        story_id,
        0,
        state,
        reading_stories,
        reading_history,
    )


@router.callback_query(F.data.startswith("stories:delete:yes:"))
async def confirm_story_delete(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    story_id = _parse_uuid(callback.data, "stories:delete:yes:")
    user = await onboarding.current_user(callback.from_user.id)
    if story_id is None or user is None:
        await callback.answer("История уже недоступна.", show_alert=True)
        return
    try:
        await reading_stories.delete(user.id, story_id)
    except ReadingStoryNotFoundError:
        await callback.answer("История уже удалена.")
    else:
        await callback.answer("История удалена")
    await _show_hub(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        reading_stories,
    )


@router.callback_query(F.data.startswith("stories:delete:"))
async def prompt_story_delete(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    story_id = _parse_uuid(callback.data, "stories:delete:")
    user = await onboarding.current_user(callback.from_user.id)
    if story_id is None or user is None:
        await callback.message.answer(_STALE)
        return
    try:
        story = await reading_stories.get(user.id, story_id)
    except ReadingStoryNotFoundError:
        await callback.message.answer(_STALE)
        return
    await show_screen(
        callback.message,
        Scene.HISTORY,
        f"Удалить историю «{escape(story.title)}»?\n\n"
        "Удалится только эта история, её название и связи. Сами разборы останутся "
        "доступны в «Все разборы».",
        reply_markup=story_delete_confirmation_keyboard(story.id),
        state=state,
    )


@router.callback_query(F.data.startswith("stories:unavailable:"))
async def unavailable_reading(callback: CallbackQuery) -> None:
    await callback.answer(
        "Этот старый тип разбора пока нельзя открыть из истории.", show_alert=True
    )


async def _show_hub(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    await state.clear()
    user = await onboarding.current_user(telegram_user_id)
    if user is None:
        await message.answer(_NOT_ONBOARDED)
        return
    stories = await reading_stories.list_for_user(user.id)
    text = (
        "📚 Мои истории\n\n"
        "Собирайте связанные разборы в одну линию — только вручную. Numa ничего не "
        "объединяет сама и не превращает такие связи в факты о вас."
    )
    if not stories:
        text += "\n\nИсторий пока нет. Создайте первую или откройте все прошлые разборы."
    await show_screen(
        message,
        Scene.HISTORY if stories else Scene.HISTORY_EMPTY,
        text,
        reply_markup=stories_hub_keyboard(stories),
        state=state,
    )


async def _show_story(
    message: Message,
    user_id: UUID,
    story_id: UUID,
    page: int,
    state: FSMContext,
    reading_stories: ReadingStoryService,
    reading_history: ReadingHistoryService,
) -> None:
    story = await reading_stories.get(user_id, story_id)
    metadata = await reading_history.ready_metadata(user_id, tuple(reversed(story.reading_ids)))
    max_page = max((len(metadata) - 1) // _PAGE_SIZE, 0)
    visible_page = min(max(page, 0), max_page)
    start = visible_page * _PAGE_SIZE
    visible = metadata[start : start + _PAGE_SIZE]
    buttons = tuple(_reading_button(item) for item in visible)
    count = len(metadata)
    body = f"📖 <b>{escape(story.title)}</b>\n\n" + (
        f"Связано разборов: {count}. Нажмите на разбор, чтобы открыть его; ✕ убирает "
        "только связь с этой историей."
        if count
        else "Здесь пока нет разборов. Добавьте любой готовый разбор вручную."
    )
    await show_screen(
        message,
        Scene.HISTORY if count else Scene.HISTORY_EMPTY,
        body,
        reply_markup=story_detail_keyboard(
            story.id,
            buttons,
            page=visible_page,
            has_next=start + _PAGE_SIZE < count,
        ),
        state=state,
    )


def _reading_button(item: ReadingHistoryChoice) -> StoryReadingButton:
    meta = _FLOW_META.get(item.persona_code)
    if meta is None:
        label = f"Разбор · {item.created_at:%d.%m.%Y}"
        callback = f"stories:unavailable:{item.reading_id}"
    else:
        topic = meta.topic_labels.get(item.topic, meta.fallback)
        label = f"{meta.emoji} {topic} · {item.created_at:%d.%m.%Y}"
        callback = f"{meta.namespace}:history:open:{item.reading_id}"
    if len(label) > 52:
        label = f"{label[:51].rstrip()}…"
    return StoryReadingButton(item.reading_id, label, callback)


def _parse_uuid(data: str | None, prefix: str) -> UUID | None:
    raw = data or ""
    if not raw.startswith(prefix):
        return None
    try:
        return UUID(raw.removeprefix(prefix))
    except ValueError:
        return None


def _parse_story_page(data: str | None, prefix: str) -> tuple[UUID, int] | None:
    raw = data or ""
    if not raw.startswith(prefix):
        return None
    value = raw.removeprefix(prefix)
    story_raw, separator, page_raw = value.rpartition(":")
    if not separator:
        story_raw, page_raw = value, "0"
    try:
        story_id = UUID(story_raw)
        page = int(page_raw)
    except ValueError:
        return None
    return story_id, max(page, 0)


def _uuid_value(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
