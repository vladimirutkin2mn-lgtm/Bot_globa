"""Question-first product packaging over the existing safe reading flows.

The underlying persona/topic handlers remain authoritative for generation, payment and
safety. This module owns only entry chrome, just-in-time consent continuity and the paid
reading value proposition, so the experiment stays reversible without a parallel oracle
engine.
"""

from dataclasses import replace

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import core_handlers, daily_conversion_handlers, persona_flows, texts
from app.bot.persona_flow import QUESTION_PROMPT, PersonaFlow, PersonaFlowTexts
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import OnboardingStates
from app.providers.analytics import OracleProductEvent
from app.services.onboarding import OnboardingService, TelegramIdentity
from app.services.oracle_product_analytics import OracleProductAnalytics

_QF_GO_PREFIX = "qf:go:"
_QF_CONSENT_PREFIX = "qf:consent:"
_QF_PRIVACY_PREFIX = "qf:privacy:"
_QF_PRIVACY_BACK_PREFIX = "qf:privacy-back:"


def question_first_menu_keyboard() -> InlineKeyboardMarkup:
    """Lead with the user's situation, while keeping personas as a secondary choice."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💞 Что происходит между нами?",
                    callback_data="qf:go:love",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔮 Что будет дальше?",
                    callback_data="qf:go:future",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚖️ Помоги выбрать: А или Б",
                    callback_data="qf:go:decision",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧿 Почему это повторяется?",
                    callback_data="qf:go:pattern",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪐 Что важно для меня сегодня?",
                    callback_data="menu:daily",
                )
            ],
            [
                InlineKeyboardButton(text="💞 Оракул", callback_data="menu:love"),
                InlineKeyboardButton(text="🔮 Таролог", callback_data="menu:tarot"),
            ],
            [
                InlineKeyboardButton(text="🌙 Психолог", callback_data="menu:psy"),
                InlineKeyboardButton(text="🪐 Астролог", callback_data="menu:astro"),
            ],
            [
                InlineKeyboardButton(text="📚 Мои разборы", callback_data="menu:readings"),
                InlineKeyboardButton(text="⋯ Ещё", callback_data="menu:more"),
            ],
        ]
    )


def question_first_onboarding_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✨ Задать вопрос", callback_data="onboarding:intro")]
        ]
    )


def daily_ritual_keyboard() -> InlineKeyboardMarkup:
    """Frame the existing personal day forecast as an intentional daily ritual."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Что важно для меня сегодня",
                    callback_data="daily:personal",
                )
            ],
            [InlineKeyboardButton(text="Настройки", callback_data="daily:settings")],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
        ]
    )


def _question_first_consent_keyboard(intent: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Принять и продолжить",
                    callback_data=f"{_QF_CONSENT_PREFIX}{intent}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Подробнее",
                    callback_data=f"{_QF_PRIVACY_PREFIX}{intent}",
                )
            ],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
        ]
    )


def _question_first_privacy_keyboard(intent: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить все мои данные",
                    callback_data="privacy:delete_all",
                )
            ],
            [
                InlineKeyboardButton(
                    text="← Назад к согласию",
                    callback_data=f"{_QF_PRIVACY_BACK_PREFIX}{intent}",
                )
            ],
        ]
    )


def _deep_reading_texts(flow_texts: PersonaFlowTexts) -> PersonaFlowTexts:
    """Replace only monetization copy; the reading engine and entitlements stay untouched."""

    return replace(
        flow_texts,
        locked=(
            "⚡ Быстрый взгляд готов.\n\n"
            "✨ Глубокий разбор раскроет связи, развилки и следующий шаг. "
            "После открытия начнётся сеанс на 24 часа — можно задать до 3 уточняющих вопросов."
        ),
        unlock_button="✨ Открыть глубокий разбор — {price}",
    )


def _identity(callback: CallbackQuery) -> TelegramIdentity:
    user = callback.from_user
    return TelegramIdentity(
        telegram_user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        language=user.language_code,
    )


def _intent(intent: str) -> tuple[PersonaFlow, str] | None:
    mapping: dict[str, tuple[PersonaFlow, str]] = {
        "love": (persona_flows.LOVE_ORACLE_FLOW, "love"),
        "future": (persona_flows.TAROT_FLOW, "general_forecast"),
        "decision": (persona_flows.TAROT_FLOW, "decision"),
        "pattern": (persona_flows.MYSTICAL_PSYCHOLOGIST_FLOW, "repeating_pattern"),
    }
    value = mapping.get(intent)
    if value is None or value[1] not in value[0].topic_labels:
        return None
    return value


async def _open_question_first_intent(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    intent: str,
    oracle_analytics: OracleProductAnalytics | None,
) -> None:
    if not isinstance(callback.message, Message):
        return
    resolved = _intent(intent)
    if resolved is None:
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            texts.MAIN_MENU,
            reply_markup=question_first_menu_keyboard(),
            state=state,
        )
        return
    flow, topic = resolved
    user = await onboarding.current_user(callback.from_user.id)
    if user is not None and oracle_analytics is not None:
        await oracle_analytics.track(
            user.id,
            OracleProductEvent.PERSONA_SELECTED,
            {"persona_code": flow.persona_code, "topic_code": topic, "entry": "question_first"},
        )
    await state.clear()
    await state.update_data(topic=topic)
    await state.set_state(flow.states.waiting_for_question)
    await show_screen(
        callback.message,
        Scene.QUESTION,
        QUESTION_PROMPT,
        state=state,
        reply_markup=flow.question_keyboard(),
    )


async def question_first_entry(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    privacy_retention_days: int,
    oracle_analytics: OracleProductAnalytics | None = None,
) -> None:
    """Open the selected topic directly, preserving it across just-in-time consent."""

    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    intent = (callback.data or "").removeprefix(_QF_GO_PREFIX)
    if _intent(intent) is None:
        return
    if await onboarding.current_user(callback.from_user.id) is None:
        await onboarding.start(_identity(callback))
    if not await onboarding.analysis_allowed(callback.from_user.id):
        await state.set_state(OnboardingStates.waiting_for_consent)
        await show_screen(
            callback.message,
            Scene.ONBOARDING_CONSENT,
            texts.CONSENT.format(days=privacy_retention_days),
            reply_markup=_question_first_consent_keyboard(intent),
            state=state,
        )
        return
    await _open_question_first_intent(callback, state, onboarding, intent, oracle_analytics)


async def question_first_accept_consent(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    oracle_analytics: OracleProductAnalytics | None = None,
) -> None:
    """Accept the same product consent as other flows, then resume the chosen question."""

    intent = (callback.data or "").removeprefix(_QF_CONSENT_PREFIX)
    if _intent(intent) is None:
        await callback.answer()
        return
    if await onboarding.current_user(callback.from_user.id) is None:
        await onboarding.start(_identity(callback))
    await onboarding.accept_consent(callback.from_user.id)
    await callback.answer()
    await _open_question_first_intent(callback, state, onboarding, intent, oracle_analytics)


async def question_first_privacy(
    callback: CallbackQuery,
    state: FSMContext,
    privacy_retention_days: int,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    intent = (callback.data or "").removeprefix(_QF_PRIVACY_PREFIX)
    if _intent(intent) is None:
        return
    await show_screen(
        callback.message,
        Scene.PRIVACY,
        texts.PRIVACY_INFO.format(days=privacy_retention_days),
        reply_markup=_question_first_privacy_keyboard(intent),
        state=state,
    )


async def question_first_privacy_back(
    callback: CallbackQuery,
    state: FSMContext,
    privacy_retention_days: int,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    intent = (callback.data or "").removeprefix(_QF_PRIVACY_BACK_PREFIX)
    if _intent(intent) is None:
        return
    await state.set_state(OnboardingStates.waiting_for_consent)
    await show_screen(
        callback.message,
        Scene.ONBOARDING_CONSENT,
        texts.CONSENT.format(days=privacy_retention_days),
        reply_markup=_question_first_consent_keyboard(intent),
        state=state,
    )


def install_question_first_cjm() -> None:
    """Install the question-first shell before the dispatcher starts serving updates."""

    texts.WELCOME = (
        "Есть вопрос, который не выходит из головы? Начните с него — Numa поможет выбрать "
        "подходящий способ посмотреть на ситуацию."
    )
    texts.MAIN_MENU = (
        "✨ О чём хочется спросить Numa?\n\n"
        "Выберите то, что ближе к вашей ситуации. Сначала покажу короткий взгляд; "
        "если захочется глубже — можно открыть полный разбор и продолжить разговор."
    )
    texts.PAYWALL = (
        "✨ Глубокий разбор по этому вопросу — {price}.\n\n"
        "После открытия начнётся сеанс на 24 часа: полный ответ и до 3 уточняющих "
        "вопросов по этому разбору без новой оплаты."
    )
    daily_conversion_handlers.PERSONAL_DAILY_PROMPT = (
        "🪐 Что важно для меня сегодня?\n\n"
        "На чём сегодня хочется сфокусироваться: отношения, работа, деньги или общее "
        "направление? Можно задать свой вопрос."
    )

    # core_handlers imports these factories directly, so replace its bound names rather
    # than the keyboard module. Payment and privacy keyboards remain untouched.
    vars(core_handlers).update(
        main_menu_keyboard=question_first_menu_keyboard,
        onboarding_intro_keyboard=question_first_onboarding_keyboard,
        daily_horoscope_keyboard=daily_ritual_keyboard,
    )
    core_handlers.router.callback_query.register(
        question_first_entry,
        F.data.startswith(_QF_GO_PREFIX),
    )
    core_handlers.router.callback_query.register(
        question_first_accept_consent,
        F.data.startswith(_QF_CONSENT_PREFIX),
    )
    core_handlers.router.callback_query.register(
        question_first_privacy,
        F.data.startswith(_QF_PRIVACY_PREFIX),
    )
    core_handlers.router.callback_query.register(
        question_first_privacy_back,
        F.data.startswith(_QF_PRIVACY_BACK_PREFIX),
    )

    tarot = replace(
        persona_flows.TAROT_FLOW,
        texts=_deep_reading_texts(persona_flows.TAROT_FLOW.texts),
    )
    love = replace(
        persona_flows.LOVE_ORACLE_FLOW,
        texts=_deep_reading_texts(persona_flows.LOVE_ORACLE_FLOW.texts),
    )
    psy = replace(
        persona_flows.MYSTICAL_PSYCHOLOGIST_FLOW,
        texts=_deep_reading_texts(persona_flows.MYSTICAL_PSYCHOLOGIST_FLOW.texts),
    )
    persona_flows.TAROT_FLOW = tarot
    persona_flows.LOVE_ORACLE_FLOW = love
    persona_flows.MYSTICAL_PSYCHOLOGIST_FLOW = psy
    persona_flows.MVP_READING_FLOWS = (tarot, love, psy)
