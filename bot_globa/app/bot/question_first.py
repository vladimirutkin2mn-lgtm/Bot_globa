"""Question-first product packaging over the existing safe reading flows.

The underlying persona/topic handlers remain authoritative for consent, generation,
payment and safety. This module changes only the entry chrome and the paid-reading
value proposition, so the experiment is reversible without introducing a parallel
oracle engine.
"""

from dataclasses import replace

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.persona_flow import PersonaFlowTexts


def question_first_menu_keyboard() -> InlineKeyboardMarkup:
    """Lead with the user's situation, while keeping personas as a secondary choice."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💞 Что происходит между нами?",
                    callback_data="love:topic:love",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔮 Что будет дальше?",
                    callback_data="tarot:topic:general_forecast",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚖️ Помоги выбрать: А или Б",
                    callback_data="tarot:topic:decision",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧿 Почему это повторяется?",
                    callback_data="psy:topic:repeating_pattern",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪐 Что важно для меня сегодня?",
                    callback_data="daily:personal",
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


def install_question_first_cjm() -> None:
    """Install the question-first shell before the dispatcher starts serving updates."""

    # Imported lazily to keep this copy-only module out of unrelated import paths.
    from app.bot import core_handlers, daily_conversion_handlers, persona_flows

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

    # core_handlers imports these factories directly, so patch its bound references rather
    # than the keyboard module. Payment and privacy keyboards remain untouched.
    core_handlers.main_menu_keyboard = question_first_menu_keyboard
    core_handlers.onboarding_intro_keyboard = question_first_onboarding_keyboard
    core_handlers.daily_horoscope_keyboard = daily_ritual_keyboard

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
