"""Continue a manual story without turning model interpretations into user facts."""

from dataclasses import dataclass
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.bot.reading_story_keyboards import (
    story_astrology_profile_keyboard,
    story_continuation_cancel_keyboard,
)
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import ReadingFollowUpStates
from app.services.birth_profile import BirthProfileConsentRequiredError, BirthProfileService
from app.services.onboarding import OnboardingService
from app.services.reading_followup import ReadingFollowUpService, ReadingFollowUpStatus
from app.services.reading_history import ReadingHistoryService
from app.services.reading_story import ReadingStoryNotFoundError, ReadingStoryService

router = Router(name="reading-story-continuation")

_NOT_ONBOARDED = "Сначала отправьте /start."
_STALE = "Эта история уже недоступна. Откройте «Мои истории» заново."
_EMPTY = "Сначала добавьте в историю хотя бы один готовый разбор."
_PROCESSING = "По последнему разбору уже готовится уточнение. Откройте историю чуть позже."
_INCLUDED_PROMPT = (
    "Что изменилось с прошлого разбора?\n\n"
    "Это уточнение входит в уже оплаченный 24-часовой сеанс: дополнительных списаний нет. "
    "Осталось вопросов в сеансе: {remaining}."
)
_NEW_SESSION_PROMPT = (
    "Что изменилось с прошлого разбора? Напишите одним сообщением.\n\n"
    "Это будет новый отдельный разбор: прошлый 24-часовой сеанс не переносится, а полный "
    "доступ, если понадобится, расходуется отдельно. Старые тексты из истории сами в новый "
    "разбор не подмешиваются; сохранённая память используется только если вы уже включили её. "
    "Когда новый разбор будет готов, его можно вручную добавить в эту историю."
)
_ASTRO_PROFILE_REQUIRED = (
    "Чтобы продолжить эту историю новым астрологическим разбором, снова нужны сохранённые "
    "данные рождения. Откройте Астролога и заполните профиль; прошлые разборы останутся в истории."
)
_UNSUPPORTED = "Этот старый тип разбора пока нельзя продолжить автоматически."


@dataclass(frozen=True, slots=True)
class _ContinuationFlow:
    question_state: State
    topics: frozenset[str]


_CONTINUATION_FLOWS = {
    TAROT_FLOW.persona_code: _ContinuationFlow(
        TAROT_FLOW.states.waiting_for_question,
        frozenset(TAROT_FLOW.topic_labels),
    ),
    LOVE_ORACLE_FLOW.persona_code: _ContinuationFlow(
        LOVE_ORACLE_FLOW.states.waiting_for_question,
        frozenset(LOVE_ORACLE_FLOW.topic_labels),
    ),
    MYSTICAL_PSYCHOLOGIST_FLOW.persona_code: _ContinuationFlow(
        MYSTICAL_PSYCHOLOGIST_FLOW.states.waiting_for_question,
        frozenset(MYSTICAL_PSYCHOLOGIST_FLOW.topic_labels),
    ),
    HOROSCOPE_FLOW.persona_code: _ContinuationFlow(
        HOROSCOPE_FLOW.states.waiting_for_question,
        frozenset(HOROSCOPE_FLOW.topic_labels),
    ),
}


@router.callback_query(F.data.startswith("stories:continue:"))
async def continue_story(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    reading_stories: ReadingStoryService,
    reading_history: ReadingHistoryService,
    reading_followups: ReadingFollowUpService,
    birth_profile_service: BirthProfileService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    story_id = _parse_uuid(callback.data, "stories:continue:")
    user = await onboarding.current_user(callback.from_user.id)
    if story_id is None or user is None:
        await callback.message.answer(_NOT_ONBOARDED if user is None else _STALE)
        return
    try:
        story = await reading_stories.get(user.id, story_id)
    except ReadingStoryNotFoundError:
        await callback.message.answer(_STALE)
        return
    metadata = await reading_history.ready_metadata(user.id, tuple(reversed(story.reading_ids)))
    if not metadata:
        await callback.message.answer(_EMPTY)
        return
    anchor = metadata[0]
    followup = await reading_followups.inspect(anchor.reading_id, user.id)
    if followup.status is ReadingFollowUpStatus.PROCESSING:
        await state.clear()
        await show_screen(
            callback.message,
            Scene.FOLLOW_UP_GENERATING,
            _PROCESSING,
            reply_markup=story_continuation_cancel_keyboard(story.id),
            state=state,
        )
        return
    if _has_included_followup(followup.status, followup.remaining_questions):
        await state.clear()
        await state.update_data(reading_id=str(anchor.reading_id))
        await state.set_state(ReadingFollowUpStates.waiting_for_question)
        await show_screen(
            callback.message,
            Scene.FOLLOW_UP_QUESTION,
            _INCLUDED_PROMPT.format(remaining=followup.remaining_questions),
            reply_markup=story_continuation_cancel_keyboard(story.id),
            state=state,
        )
        return

    flow = _CONTINUATION_FLOWS.get(anchor.persona_code)
    if flow is None or anchor.topic not in flow.topics:
        await callback.message.answer(_UNSUPPORTED)
        return
    if anchor.persona_code == HOROSCOPE_FLOW.persona_code:
        try:
            profile = await birth_profile_service.load(user.id)
        except BirthProfileConsentRequiredError:
            profile = None
        if profile is None:
            await state.clear()
            await show_screen(
                callback.message,
                Scene.ASTRO_PROFILE,
                _ASTRO_PROFILE_REQUIRED,
                reply_markup=story_astrology_profile_keyboard(story.id),
                state=state,
            )
            return

    await state.clear()
    await state.update_data(topic=anchor.topic)
    await state.set_state(flow.question_state)
    await show_screen(
        callback.message,
        Scene.QUESTION,
        _NEW_SESSION_PROMPT,
        reply_markup=story_continuation_cancel_keyboard(story.id),
        state=state,
    )


def _has_included_followup(status: ReadingFollowUpStatus, remaining_questions: int) -> bool:
    if remaining_questions <= 0:
        return False
    return status in {
        ReadingFollowUpStatus.READY,
        ReadingFollowUpStatus.COMPLETED,
        ReadingFollowUpStatus.CORRUPTED_HISTORY,
    }


def _parse_uuid(data: str | None, prefix: str) -> UUID | None:
    raw = data or ""
    if not raw.startswith(prefix):
        return None
    try:
        return UUID(raw.removeprefix(prefix))
    except ValueError:
        return None
