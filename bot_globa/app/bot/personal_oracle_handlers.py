"""One personal-oracle entry point over the existing reading mechanics."""

from __future__ import annotations

import re
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import texts
from app.bot.horoscope_handlers import HoroscopeHandlers
from app.bot.persona_flow import QUESTION_LIMIT, PersonaFlow
from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.bot.persona_handlers import PersonaReadingHandlers, PersonaReadings
from app.bot.safety_intake import SafetyIntake, state_name
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import IntakeStates, OnboardingStates
from app.providers.analytics import OracleProductEvent
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService, TelegramIdentity
from app.services.oracle_product_analytics import OracleProductAnalytics

router = Router(name="personal_oracle")

AUTO_CALLBACK = "oracle:auto"
TAROT_CALLBACK = "oracle:tarot"
LOVE_CALLBACK = "oracle:love"
ASTRO_CALLBACK = "oracle:astro"
_CONSENT_PREFIX = "oracle:consent:"
_ROUTE_PREFIX = "oracle:route:"
_PENDING_QUESTION_KEY = "personal_oracle_pending_question"
_DIRECT_MODE_KEY = "personal_oracle_mode"
_DIRECT_PRACTICES = frozenset({"tarot", "love"})

AUTO_PROMPT = (
    "✨ <b>Расскажите Numa</b>\n\n"
    "Опишите одним сообщением, что происходит и что больше всего не даёт покоя. "
    "Не нужно выбирать практику или формулировать вопрос особым образом — Numa сама поймёт, "
    "какой способ разбора здесь уместнее."
)
ROUTE_CLARIFICATION = "Здесь можно посмотреть на ситуацию по-разному. Что для вас сейчас главное?"
INVALID_QUESTION = "Расскажите ситуацию обычным текстовым сообщением до 8000 символов."


@dataclass(frozen=True, slots=True)
class RouteChoice:
    flow: PersonaFlow
    topic: str


_STRONG_LOVE_RE = re.compile(
    r"(любов|люблю|влюб|бывш|муж\b|жена\b|парень|девуш|между нами|свидан|расстал|"
    r"верн[её]т|ревну|\bизмен(?:а|ы|е|у|ой)\b|"
    r"(?:изменил|изменила|изменяет)\s+(?:мне|ему|ей)\b|"
    r"написать (?:ему|ей)|позвонить (?:ему|ей)|"
    r"\b(?:он|она)\b.{0,30}(?:ко мне )?чувств|любит ли|нравлюсь ли|отношение ко мне)",
    re.IGNORECASE,
)
_BROAD_RELATIONSHIP_RE = re.compile(r"(отношен)", re.IGNORECASE)
_RELATIONSHIP_CHANGE_RE = re.compile(
    r"(отношен\w*.{0,40}\bизмен(?:ил|ила|ились|илось|яется|яются)\b)",
    re.IGNORECASE,
)
_REFLECTION_RE = re.compile(
    r"(почему я|почему у меня|повторя|снова и снова|постоянно одно и то же|паттерн|"
    r"самосабот|не могу перестать|боюсь|страх|тревог|выгора|тянет к|недоступн\w*|"
    r"внутренн(?:ий|яя) конфликт)",
    re.IGNORECASE,
)
_COMMUNICATION_RE = re.compile(r"(написать|позвонить|проявит|ответить|связаться)", re.IGNORECASE)
_FEELINGS_RE = re.compile(r"(чувств|любит|нравлюсь|отношение ко мне)", re.IGNORECASE)
_RELATIONSHIP_DIRECTION_RE = re.compile(
    r"(куда (?:вс[её]|это) (?:ид[её]т|движ)|что будет между|будем ли вместе|есть ли будущее)",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(r"(выбрать|выбор|вариант|решени|стоит ли|что лучше)", re.IGNORECASE)
_WORK_RE = re.compile(
    r"(работ|начальник|руководител|коллег|карьер|деньг|финанс|бизнес|проект|увол|"
    r"офер|предложени[ея] по работе)",
    re.IGNORECASE,
)
_REPEAT_RE = re.compile(
    r"(повторя|\bснова\b|\bопять\b|снова и снова|одно и то же|по кругу|паттерн)",
    re.IGNORECASE,
)


class PlainTextBeforeConsentFilter(BaseFilter):
    """Match a real question before consent without swallowing slash commands."""

    async def __call__(self, message: Message) -> bool:
        return bool(message.text and not message.text.lstrip().startswith("/"))


def choose_route(question: str) -> RouteChoice:
    """Choose the existing mechanic using strong intent and surrounding context."""

    value = _normalized(question)
    if _WORK_RE.search(value):
        return RouteChoice(TAROT_FLOW, "work")
    if _STRONG_LOVE_RE.search(value):
        return _love_route(value)
    if _REFLECTION_RE.search(value):
        topic = "repeating_pattern" if _REPEAT_RE.search(value) else "self_reflection"
        return RouteChoice(MYSTICAL_PSYCHOLOGIST_FLOW, topic)
    if _DECISION_RE.search(value):
        return RouteChoice(TAROT_FLOW, "decision")
    return RouteChoice(TAROT_FLOW, "general_forecast")


def needs_route_clarification(question: str) -> bool:
    """Ask once when relationship intent is broad or materially mixed with another context."""

    value = _normalized(question)
    strong_love = bool(_STRONG_LOVE_RE.search(value))
    broad_relationship = bool(_BROAD_RELATIONSHIP_RE.search(value))
    work = bool(_WORK_RE.search(value))
    reflection = bool(_REFLECTION_RE.search(value))
    decision = bool(_DECISION_RE.search(value))
    if strong_love and work:
        return True
    if broad_relationship and work:
        return bool(_RELATIONSHIP_CHANGE_RE.search(value))
    if strong_love and reflection:
        return True
    if not broad_relationship:
        return False
    return not any((strong_love, reflection, decision))


def route_within_practice(question: str, mode: str) -> RouteChoice | None:
    """Keep an explicit practice while choosing the most relevant topic inside it."""

    value = _normalized(question)
    if mode == "love":
        return _love_route(value)
    if mode != "tarot":
        return None
    if _WORK_RE.search(value):
        topic = "work"
    elif _DECISION_RE.search(value):
        topic = "decision"
    elif _REPEAT_RE.search(value):
        topic = "repeating_pattern"
    elif _STRONG_LOVE_RE.search(value) or _BROAD_RELATIONSHIP_RE.search(value):
        topic = "love"
    else:
        topic = "general_forecast"
    return RouteChoice(TAROT_FLOW, topic)


def route_from_clarification(question: str, mode: str) -> RouteChoice | None:
    """Honor the user's explicit practice choice for one stored ambiguous question."""

    value = _normalized(question)
    if mode == "love":
        return _love_route(value)
    if mode == "reflection":
        topic = "repeating_pattern" if _REPEAT_RE.search(value) else "self_reflection"
        return RouteChoice(MYSTICAL_PSYCHOLOGIST_FLOW, topic)
    if mode == "work":
        topic = "decision" if _DECISION_RE.search(value) else "work"
        return RouteChoice(TAROT_FLOW, topic)
    return None


def personal_oracle_safety_intake() -> SafetyIntake:
    """Protect the free-form Numa entry before its question is routed to a persona."""

    return SafetyIntake(
        persona_code="personal_oracle",
        question_state=state_name(IntakeStates.waiting_for_conversation),
        handoff_keyboard=_question_keyboard,
    )


@router.callback_query(F.data.in_({AUTO_CALLBACK, TAROT_CALLBACK, LOVE_CALLBACK}))
async def start_personal_oracle(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    privacy_retention_days: int,
    oracle_analytics: OracleProductAnalytics | None = None,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    mode = (callback.data or "").removeprefix("oracle:")
    await _ensure_user(callback, onboarding)
    if not await onboarding.analysis_allowed(callback.from_user.id):
        await _ask_consent(callback.message, state, privacy_retention_days, mode)
        return
    await _open_mode(
        callback.message,
        callback.from_user.id,
        state,
        mode,
        onboarding,
        oracle_analytics,
    )


@router.callback_query(F.data == ASTRO_CALLBACK)
async def start_astrology(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    privacy_retention_days: int,
) -> None:
    await _ensure_user(callback, onboarding)
    if not await onboarding.analysis_allowed(callback.from_user.id):
        await callback.answer()
        if isinstance(callback.message, Message):
            await _ask_consent(callback.message, state, privacy_retention_days, "astro")
        return
    await HoroscopeHandlers().start_from_menu(
        callback,
        state,
        onboarding,
        birth_profile_service,
        privacy_retention_days,
    )


@router.message(OnboardingStates.waiting_for_consent, PlainTextBeforeConsentFilter())
async def capture_question_before_consent(
    message: Message,
    state: FSMContext,
    privacy_retention_days: int,
) -> None:
    """Preserve first-screen text and ask consent before any routing or generation."""

    question = _bounded_text(message)
    if question is None:
        await message.answer(INVALID_QUESTION)
        return
    data = await state.get_data()
    raw_mode = data.get(_DIRECT_MODE_KEY)
    mode = (
        raw_mode
        if isinstance(raw_mode, str) and raw_mode in {*_DIRECT_PRACTICES, "astro"}
        else "auto"
    )
    update: dict[str, str] = {_DIRECT_MODE_KEY: mode}
    if mode != "astro":
        update[_PENDING_QUESTION_KEY] = question
    await state.update_data(update)
    await state.set_state(OnboardingStates.waiting_for_consent)
    await show_screen(
        message,
        Scene.ONBOARDING_CONSENT,
        texts.CONSENT.format(days=privacy_retention_days),
        reply_markup=_consent_keyboard(mode),
        state=state,
    )


@router.callback_query(F.data.startswith(_CONSENT_PREFIX))
async def accept_personal_oracle_consent(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    privacy_retention_days: int,
    persona_readings: PersonaReadings,
    oracle_analytics: OracleProductAnalytics | None = None,
) -> None:
    mode = (callback.data or "").removeprefix(_CONSENT_PREFIX)
    if mode not in {"auto", "tarot", "love", "astro"}:
        await callback.answer()
        return
    data = await state.get_data()
    question = data.get(_PENDING_QUESTION_KEY)
    await _ensure_user(callback, onboarding)
    await onboarding.accept_consent(callback.from_user.id)
    if mode == "astro":
        await HoroscopeHandlers().start_from_menu(
            callback,
            state,
            onboarding,
            birth_profile_service,
            privacy_retention_days,
        )
        return
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if isinstance(question, str) and question.strip():
        await _continue_pending_question(
            callback.message,
            callback.from_user.id,
            question,
            mode,
            state,
            onboarding,
            persona_readings,
            oracle_analytics,
        )
        return
    await _open_mode(
        callback.message,
        callback.from_user.id,
        state,
        mode,
        onboarding,
        oracle_analytics,
    )


@router.callback_query(F.data.startswith(_ROUTE_PREFIX))
async def choose_personal_route(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    persona_readings: PersonaReadings,
    oracle_analytics: OracleProductAnalytics | None = None,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    question = data.get(_PENDING_QUESTION_KEY)
    if not isinstance(question, str) or not question.strip():
        await state.clear()
        await state.set_state(IntakeStates.waiting_for_conversation)
        await show_screen(
            callback.message,
            Scene.QUESTION,
            AUTO_PROMPT,
            reply_markup=_question_keyboard(),
            state=state,
        )
        return
    mode = (callback.data or "").removeprefix(_ROUTE_PREFIX)
    choice = route_from_clarification(question, mode)
    if choice is None:
        return
    await _generate_routed_question(
        callback.message,
        callback.from_user.id,
        question,
        choice,
        state,
        onboarding,
        persona_readings,
        oracle_analytics,
    )


@router.message(IntakeStates.waiting_for_conversation)
async def receive_personal_question(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    persona_readings: PersonaReadings,
    privacy_retention_days: int,
    oracle_analytics: OracleProductAnalytics | None = None,
) -> None:
    if message.from_user is None:
        return
    question = _bounded_text(message)
    if question is None:
        await show_screen(
            message,
            Scene.QUESTION_ERROR,
            INVALID_QUESTION,
            reply_markup=_question_keyboard(),
            state=state,
        )
        return
    data = await state.get_data()
    raw_mode = data.get(_DIRECT_MODE_KEY)
    mode = raw_mode if isinstance(raw_mode, str) and raw_mode in _DIRECT_PRACTICES else "auto"
    if mode == "auto" and needs_route_clarification(question):
        await state.update_data({_PENDING_QUESTION_KEY: question, _DIRECT_MODE_KEY: "auto"})
        await show_screen(
            message,
            Scene.QUESTION,
            ROUTE_CLARIFICATION,
            reply_markup=_route_clarification_keyboard(),
            state=state,
        )
        return
    choice = (
        route_within_practice(question, mode)
        if mode in _DIRECT_PRACTICES
        else choose_route(question)
    )
    if choice is None:
        return
    await _generate_routed_question(
        message,
        message.from_user.id,
        question,
        choice,
        state,
        onboarding,
        persona_readings,
        oracle_analytics,
    )


async def _continue_pending_question(
    message: Message,
    telegram_user_id: int,
    question: str,
    mode: str,
    state: FSMContext,
    onboarding: OnboardingService,
    persona_readings: PersonaReadings,
    oracle_analytics: OracleProductAnalytics | None,
) -> None:
    if mode == "auto" and needs_route_clarification(question):
        await state.clear()
        await state.update_data({_PENDING_QUESTION_KEY: question, _DIRECT_MODE_KEY: "auto"})
        await state.set_state(IntakeStates.waiting_for_conversation)
        await show_screen(
            message,
            Scene.QUESTION,
            ROUTE_CLARIFICATION,
            reply_markup=_route_clarification_keyboard(),
            state=state,
        )
        return
    choice = (
        route_within_practice(question, mode)
        if mode in _DIRECT_PRACTICES
        else choose_route(question)
    )
    if choice is None:
        return
    await _generate_routed_question(
        message,
        telegram_user_id,
        question,
        choice,
        state,
        onboarding,
        persona_readings,
        oracle_analytics,
    )


async def _generate_routed_question(
    message: Message,
    telegram_user_id: int,
    question: str,
    choice: RouteChoice,
    state: FSMContext,
    onboarding: OnboardingService,
    persona_readings: PersonaReadings,
    oracle_analytics: OracleProductAnalytics | None,
) -> None:
    await state.clear()
    await state.update_data(topic=choice.topic, question=question)
    await state.set_state(choice.flow.states.waiting_for_question)
    if oracle_analytics is not None:
        user = await onboarding.current_user(telegram_user_id)
        if user is not None:
            await oracle_analytics.track(
                user.id,
                OracleProductEvent.PERSONA_SELECTED,
                {
                    "persona_code": choice.flow.persona_code,
                    "topic_code": choice.topic,
                },
            )
    await PersonaReadingHandlers(choice.flow)._generate_new(
        message,
        telegram_user_id,
        state,
        onboarding,
        persona_readings,
        context=None,
    )


async def _open_mode(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
    mode: str,
    onboarding: OnboardingService,
    oracle_analytics: OracleProductAnalytics | None,
) -> None:
    await state.clear()
    await state.update_data({_DIRECT_MODE_KEY: mode})
    await state.set_state(IntakeStates.waiting_for_conversation)
    prompt = AUTO_PROMPT if mode == "auto" else _mechanic_prompt(mode)
    await show_screen(
        message,
        Scene.QUESTION,
        prompt,
        reply_markup=_question_keyboard(),
        state=state,
    )


async def _ensure_user(callback: CallbackQuery, onboarding: OnboardingService) -> None:
    if await onboarding.current_user(callback.from_user.id) is not None:
        return
    user = callback.from_user
    await onboarding.start(
        TelegramIdentity(
            telegram_user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            language=user.language_code,
        )
    )


async def _ask_consent(
    message: Message,
    state: FSMContext,
    privacy_retention_days: int,
    mode: str,
) -> None:
    await state.clear()
    await state.update_data({_DIRECT_MODE_KEY: mode})
    await state.set_state(OnboardingStates.waiting_for_consent)
    await show_screen(
        message,
        Scene.ONBOARDING_CONSENT,
        texts.CONSENT.format(days=privacy_retention_days),
        reply_markup=_consent_keyboard(mode),
        state=state,
    )


def _consent_keyboard(mode: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Принять и продолжить",
                    callback_data=f"{_CONSENT_PREFIX}{mode}",
                )
            ],
            [InlineKeyboardButton(text="Подробнее", callback_data="menu:privacy")],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
        ]
    )


def _route_clarification_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💞 Личные отношения",
                    callback_data=f"{_ROUTE_PREFIX}love",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌙 О себе и состоянии",
                    callback_data=f"{_ROUTE_PREFIX}reflection",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧭 Работа или выбор",
                    callback_data=f"{_ROUTE_PREFIX}work",
                )
            ],
            [InlineKeyboardButton(text="← В главное меню", callback_data="menu:home")],
        ]
    )


def _question_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← В главное меню", callback_data="menu:home")],
        ]
    )


def _mechanic_prompt(mode: str) -> str:
    if mode == "tarot":
        return (
            "🔮 <b>Таро</b>\n\n"
            "Задайте вопрос своими словами. Не нужно выбирать тему: отношения, работа, решение "
            "или будущее — расклад соберётся под сам вопрос."
        )
    return (
        "💞 <b>Любовный оракул</b>\n\n"
        "Расскажите о человеке или ситуации между вами и напишите, что хотите понять. "
        "Numa сама выберет, на какую сторону этой истории посмотреть глубже."
    )


def _love_route(value: str) -> RouteChoice:
    if _COMMUNICATION_RE.search(value):
        topic = "communication"
    elif _FEELINGS_RE.search(value):
        topic = "love"
    elif _REPEAT_RE.search(value):
        topic = "repeating_pattern"
    elif _RELATIONSHIP_DIRECTION_RE.search(value):
        topic = "choice"
    else:
        topic = "boundaries"
    return RouteChoice(LOVE_ORACLE_FLOW, topic)


def _normalized(question: str) -> str:
    return " ".join(question.casefold().split())


def _bounded_text(message: Message) -> str | None:
    if message.text is None:
        return None
    value = message.text.strip()
    if not value or len(value) > QUESTION_LIMIT:
        return None
    return value
