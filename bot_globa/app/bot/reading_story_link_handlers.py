"""Save a just-finished reading into a user-owned story."""

from collections.abc import Sequence
from contextlib import suppress
from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.reading_story_context import DIRECT_STORY_LINK_PREFIX, parse_direct_story_link
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.domain.reading_story import ReadingStoryView
from app.services.onboarding import OnboardingService
from app.services.reading_story import (
    ReadingStoryNotFoundError,
    ReadingStoryReadingError,
    ReadingStoryService,
    ReadingStoryTitleError,
)

router = Router(name="reading-story-link")

_LINK_READING_KEY = "reading_story_link_reading_id"
_LINK_PREFIX = "stories:link:"
_LINK_TO_PREFIX = "stories:link-to:"
_NEW_CALLBACK = "stories:link-new"
_MAX_STORIES = 8
_NOT_ONBOARDED = "Сначала отправьте /start."
_STALE_READING = "Этот разбор уже недоступен. Откройте «Мои истории» заново."


class ReadingStoryLinkStates(StatesGroup):
    waiting_for_title = State()


def story_picker_keyboard(stories: Sequence[ReadingStoryView]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=story.title,
                callback_data=f"{_LINK_TO_PREFIX}{story.id}",
            )
        ]
        for story in stories[:_MAX_STORIES]
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="＋ Новая история", callback_data=_NEW_CALLBACK)],
            [InlineKeyboardButton(text="← К моим историям", callback_data="menu:readings")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def linked_keyboard(story_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть историю",
                    callback_data=f"stories:open:{story_id}:0",
                )
            ],
            [InlineKeyboardButton(text="← К моим историям", callback_data="menu:readings")],
        ]
    )


@router.callback_query(F.data.startswith(DIRECT_STORY_LINK_PREFIX))
async def link_directly_to_story(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    target = parse_direct_story_link(callback.data)
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or target is None:
        await callback.answer(
            _NOT_ONBOARDED if user is None else _STALE_READING,
            show_alert=True,
        )
        return
    story_id, reading_id = target
    try:
        await reading_stories.link_reading(user.id, story_id, reading_id)
        story = await reading_stories.get(user.id, story_id)
    except ReadingStoryNotFoundError:
        await callback.answer("Эта история уже недоступна.", show_alert=True)
        return
    except ReadingStoryReadingError:
        await callback.answer(_STALE_READING, show_alert=True)
        return

    await callback.answer("Разбор добавлен")
    await state.clear()
    await show_screen(
        callback.message,
        Scene.HISTORY,
        f"Разбор добавлен в «{escape(story.title)}».",
        reply_markup=linked_keyboard(story.id),
        state=state,
    )


@router.callback_query(F.data.startswith(_LINK_PREFIX))
async def begin_link_reading(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    reading_id = _parse_uuid(callback.data, _LINK_PREFIX)
    user = await onboarding.current_user(callback.from_user.id)
    if reading_id is None or user is None:
        await callback.message.answer(_NOT_ONBOARDED if user is None else _STALE_READING)
        return

    stories = await reading_stories.list_for_user(user.id)
    await state.clear()
    await state.update_data({_LINK_READING_KEY: str(reading_id)})
    prompt = (
        "К какой истории добавить этот разбор?\n\n"
        "Если разбор уже связан с другой историей, он будет перенесён сюда. Сам разбор "
        "не изменится."
    )
    if not stories:
        prompt = "Историй пока нет. Создайте первую — этот разбор добавится в неё автоматически."
    elif len(stories) > _MAX_STORIES:
        prompt += f"\n\nПоказываю {_MAX_STORIES} последних историй."
    await show_screen(
        callback.message,
        Scene.HISTORY,
        prompt,
        reply_markup=story_picker_keyboard(stories),
        state=state,
    )


@router.callback_query(F.data.startswith(_LINK_TO_PREFIX))
async def link_to_story(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    story_id = _parse_uuid(callback.data, _LINK_TO_PREFIX)
    reading_id = _pending_reading_id(await state.get_data())
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or story_id is None or reading_id is None:
        await callback.answer(
            "Откройте разбор и выберите «Добавить в историю» ещё раз.",
            show_alert=True,
        )
        return
    try:
        await reading_stories.link_reading(user.id, story_id, reading_id)
        story = await reading_stories.get(user.id, story_id)
    except ReadingStoryNotFoundError:
        await callback.answer("Эта история уже недоступна.", show_alert=True)
        return
    except ReadingStoryReadingError:
        await state.clear()
        await callback.answer(_STALE_READING, show_alert=True)
        return

    await callback.answer("Разбор добавлен")
    await state.clear()
    await show_screen(
        callback.message,
        Scene.HISTORY,
        f"Разбор добавлен в «{escape(story.title)}».",
        reply_markup=linked_keyboard(story.id),
        state=state,
    )


@router.callback_query(F.data == _NEW_CALLBACK)
async def begin_new_story(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    reading_id = _pending_reading_id(await state.get_data())
    if await onboarding.current_user(callback.from_user.id) is None:
        await state.clear()
        await callback.message.answer(_NOT_ONBOARDED)
        return
    if reading_id is None:
        await callback.message.answer(_STALE_READING)
        return
    await state.set_state(ReadingStoryLinkStates.waiting_for_title)
    await show_screen(
        callback.message,
        Scene.HISTORY,
        "Как назвать новую историю?\n\n"
        "Например: «Новая работа», «Отношения» или «Переезд». После создания этот разбор "
        "добавится туда автоматически.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="menu:readings")],
            ]
        ),
        state=state,
    )


@router.message(ReadingStoryLinkStates.waiting_for_title)
async def create_story_and_link(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
) -> None:
    if message.from_user is None:
        return
    user = await onboarding.current_user(message.from_user.id)
    reading_id = _pending_reading_id(await state.get_data())
    if user is None or reading_id is None:
        await state.clear()
        await message.answer(_NOT_ONBOARDED if user is None else _STALE_READING)
        return

    try:
        story = await reading_stories.create(user.id, message.text or "")
    except ReadingStoryTitleError:
        await show_screen(
            message,
            Scene.HISTORY,
            "Название должно быть непустым и не длиннее 120 символов. Попробуйте ещё раз.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data="menu:readings")],
                ]
            ),
            state=state,
        )
        return

    try:
        await reading_stories.link_reading(user.id, story.id, reading_id)
    except (ReadingStoryNotFoundError, ReadingStoryReadingError):
        with suppress(ReadingStoryNotFoundError):
            await reading_stories.delete(user.id, story.id)
        await state.clear()
        await message.answer(_STALE_READING)
        return

    await state.clear()
    await show_screen(
        message,
        Scene.HISTORY,
        f"История «{escape(story.title)}» создана, разбор добавлен.",
        reply_markup=linked_keyboard(story.id),
        state=state,
    )


def _pending_reading_id(data: dict[str, object]) -> UUID | None:
    value = data.get(_LINK_READING_KEY)
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _parse_uuid(data: str | None, prefix: str) -> UUID | None:
    value = (data or "").removeprefix(prefix)
    try:
        return UUID(value)
    except ValueError:
        return None
