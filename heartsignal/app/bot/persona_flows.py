"""The MVP reading flows: namespace, topics and Russian copy for each persona.

This module is data. Behavior lives in `app.bot.persona_handlers`, symbols in
`app.services.symbolic_engine`, and the persona contract itself in `app.domain.persona`.
Callback namespaces are deliberately short: Telegram caps callback data at 64 bytes and
a payload already carries a 36-character reading UUID.
"""

from types import MappingProxyType

from app.bot.persona_flow import PersonaFlow, PersonaFlowTexts
from app.bot.reading_renderer import ReadingCopy
from app.bot.states import LoveOracleStates, MysticalPsychologistStates, TarotStates

TAROT_TOPIC_LABELS = MappingProxyType(
    {
        "love": "Отношения",
        "work": "Работа",
        "decision": "Выбор",
        "repeating_pattern": "Повторяющаяся ситуация",
        "general_forecast": "Общий расклад",
    }
)

LOVE_ORACLE_TOPIC_LABELS = MappingProxyType(
    {
        "love": "Отношения",
        "communication": "Общение",
        "boundaries": "Границы",
        "choice": "Выбор",
        "repeating_pattern": "Повторяющаяся ситуация",
    }
)

MYSTICAL_PSYCHOLOGIST_TOPIC_LABELS = MappingProxyType(
    {
        "self_reflection": "Взгляд на себя",
        "repeating_pattern": "Повторяющийся сценарий",
        "decision": "Выбор",
        "work": "Работа",
        "love": "Отношения",
    }
)


def _reflection_texts(*, welcome: str, unavailable: str) -> PersonaFlowTexts:
    """Copy shared by the personas whose answer is a discussion, not a card spread."""
    return PersonaFlowTexts(
        welcome=welcome,
        processing="Вопрос зафиксирован. Собираю разбор…",
        opening="Открываю сохранённый разбор…",
        already_processing="Этот разбор уже обрабатывается. Откройте его немного позже.",
        unavailable=unavailable,
        failed="Не удалось завершить разбор. Вопрос сохранён, поэтому попытку можно повторить.",
        history_title="Ваши последние готовые разборы:",
        history_empty="Готовых разборов пока нет.",
        history_fallback="Разбор",
        locked=(
            "Разбор готов. Бесплатный preview уже использован — "
            "откройте полный разбор за {price} кр."
        ),
        unlock_failed="Не удалось открыть полный разбор. Списание отменено или возвращено.",
        unlock_button="Открыть полный разбор за {price} кр.",
        new_button="Новый разбор",
        history_button="Мои разборы",
    )


TAROT_FLOW = PersonaFlow(
    persona_code="tarot_reader",
    namespace="tarot",
    states=TarotStates,
    topic_labels=TAROT_TOPIC_LABELS,
    texts=PersonaFlowTexts(
        welcome=(
            "🔮 Таролог\n\nВыберите тему. Карты выбираются приложением и не меняются при "
            "повторе. Результат предназначен для развлечения и рефлексии."
        ),
        processing="Расклад зафиксирован. Собираю интерпретацию…",
        opening="Открываю сохранённый расклад…",
        already_processing="Этот расклад уже обрабатывается. Откройте его немного позже.",
        unavailable="Таролог временно недоступен. Начните новый расклад позже.",
        failed=(
            "Не удалось завершить интерпретацию. Карты сохранены, поэтому попытку можно повторить."
        ),
        history_title="Ваши последние готовые расклады:",
        history_empty="Готовых раскладов пока нет.",
        history_fallback="Расклад",
        locked=(
            "Расклад готов. Бесплатный preview уже использован — "
            "откройте полный разбор за {price} кр."
        ),
        unlock_failed="Не удалось открыть полный расклад. Списание отменено или возвращено.",
        unlock_button="Открыть полный расклад за {price} кр.",
        new_button="Новый расклад",
        history_button="Мои расклады",
    ),
    copy=ReadingCopy(
        emoji="🔮",
        full_title_prefix="Полный расклад",
        drawn_symbols_title="Ваш расклад:",
        result_symbols_title="Карты и позиции:",
    ),
)

LOVE_ORACLE_FLOW = PersonaFlow(
    persona_code="love_oracle",
    namespace="love",
    states=LoveOracleStates,
    topic_labels=LOVE_ORACLE_TOPIC_LABELS,
    texts=_reflection_texts(
        welcome=(
            "💞 Любовный оракул\n\nВыберите тему. Разбор говорит о наблюдаемой динамике, "
            "границах и ваших решениях — он не читает мысли другого человека и не обещает "
            "конкретный исход."
        ),
        unavailable="Любовный оракул временно недоступен. Начните новый разбор позже.",
    ),
    copy=ReadingCopy(
        emoji="💞",
        full_title_prefix="Полный разбор",
        drawn_symbols_title="Опоры разбора:",
        result_symbols_title="Разбор по частям:",
    ),
)

MYSTICAL_PSYCHOLOGIST_FLOW = PersonaFlow(
    persona_code="mystical_psychologist",
    namespace="psy",
    states=MysticalPsychologistStates,
    topic_labels=MYSTICAL_PSYCHOLOGIST_TOPIC_LABELS,
    texts=_reflection_texts(
        welcome=(
            "🌙 Мистический психолог\n\nВыберите тему. Это метафорическая рефлексия об "
            "архетипах и повторяющихся сценариях — не диагноз, не терапия и не утверждение "
            "о вашей личности."
        ),
        unavailable="Мистический психолог временно недоступен. Начните новый разбор позже.",
    ),
    copy=ReadingCopy(
        emoji="🌙",
        full_title_prefix="Полный разбор",
        drawn_symbols_title="Опоры рефлексии:",
        result_symbols_title="Разбор по частям:",
    ),
)

MVP_READING_FLOWS: tuple[PersonaFlow, ...] = (
    TAROT_FLOW,
    LOVE_ORACLE_FLOW,
    MYSTICAL_PSYCHOLOGIST_FLOW,
)
