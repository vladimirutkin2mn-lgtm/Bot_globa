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
        "work": "Работа и деньги",
        "decision": "Выбор",
        "repeating_pattern": "Почему это повторяется",
        "general_forecast": "Свой вопрос",
    }
)
TAROT_TOPIC_EXAMPLES = MappingProxyType(
    {
        "love": "мы стали реже общаться; хочу понять динамику и свой следующий шаг",
        "work": "выбираю между текущей работой и новым предложением; что важно учесть",
        "decision": "у меня два варианта; чего я могу не замечать в каждом из них",
        "repeating_pattern": "я снова откладываю важное решение; почему так происходит",
        "general_forecast": "какая тема сейчас больше всего требует моего внимания",
    }
)

LOVE_ORACLE_TOPIC_LABELS = MappingProxyType(
    {
        "love": "Что происходит между нами",
        "communication": "Стоит ли проявиться",
        "choice": "Куда всё движется",
        "repeating_pattern": "Почему это повторяется",
        "boundaries": "Свой вопрос",
    }
)
LOVE_ORACLE_TOPIC_EXAMPLES = MappingProxyType(
    {
        "love": "мы сблизились, а затем человек отдалился; хочу увидеть динамику со стороны",
        "communication": "думаю написать после паузы; хочу выбрать уважительный следующий шаг",
        "choice": "отношения неопределённые; хочу понять возможные сценарии и свои границы",
        "repeating_pattern": "в отношениях я снова беру всю инициативу на себя",
        "boundaries": "мне трудно отказать; как обозначить границу без давления",
    }
)

MYSTICAL_PSYCHOLOGIST_TOPIC_LABELS = MappingProxyType(
    {
        "repeating_pattern": "Повторяющийся сценарий",
        "decision": "Сложный выбор",
        "work": "Работа",
        "love": "Отношения",
        "self_reflection": "Свой вопрос",
    }
)
MYSTICAL_PSYCHOLOGIST_TOPIC_EXAMPLES = MappingProxyType(
    {
        "repeating_pattern": "я берусь за новое, но отступаю перед первым заметным результатом",
        "decision": "одна часть меня хочет перемен, другая держится за безопасность",
        "work": "после рабочих встреч долго сомневаюсь в каждом своём слове",
        "love": "мне трудно говорить о потребностях, пока напряжение не накопится",
        "self_reflection": "хочу понять, почему сейчас так остро реагирую на неопределённость",
    }
)


def _reflection_texts(*, welcome: str, unavailable: str) -> PersonaFlowTexts:
    """Copy shared by the personas whose answer is a discussion, not a card spread."""
    return PersonaFlowTexts(
        welcome=welcome,
        processing=(
            "Вопрос принят. Фиксирую опоры и собираю разбор — обычно это занимает до 30 секунд."
        ),
        opening="Открываю сохранённый разбор…",
        already_processing="Этот разбор уже обрабатывается. Откройте его немного позже.",
        unavailable=unavailable,
        failed="Не удалось завершить разбор. Вопрос сохранён, поэтому попытку можно повторить.",
        history_title="Ваши последние готовые разборы:",
        history_empty="Готовых разборов пока нет.",
        history_fallback="Разбор",
        locked="Разбор готов. Откройте полный разбор за {price}.",
        unlock_failed="Не удалось открыть полный разбор. Списание отменено или возвращено.",
        unlock_button="Открыть полный разбор — {price}",
        new_button="Новый разбор",
        history_button="Мои разборы",
    )


TAROT_FLOW = PersonaFlow(
    persona_code="tarot_reader",
    namespace="tarot",
    states=TarotStates,
    topic_labels=TAROT_TOPIC_LABELS,
    topic_examples=TAROT_TOPIC_EXAMPLES,
    texts=PersonaFlowTexts(
        welcome=(
            "Что хотите прояснить? Карты фиксируются один раз до интерпретации, поэтому "
            "ответ не подгоняется под вопрос.\n\nЭто развлекательная практика для рефлексии."
        ),
        processing=(
            "Вопрос принят. Фиксирую опоры и собираю разбор — обычно это занимает до 30 секунд."
        ),
        opening="Открываю сохранённый расклад…",
        already_processing="Этот расклад уже обрабатывается. Откройте его немного позже.",
        unavailable="Таролог временно недоступен. Начните новый расклад позже.",
        failed=(
            "Не удалось завершить интерпретацию. Карты сохранены, поэтому попытку можно повторить."
        ),
        history_title="Ваши последние готовые расклады:",
        history_empty="Готовых раскладов пока нет.",
        history_fallback="Расклад",
        locked="Расклад готов. Откройте полный разбор за {price}.",
        unlock_failed="Не удалось открыть полный расклад. Списание отменено или возвращено.",
        unlock_button="Открыть полный разбор — {price}",
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
    topic_examples=LOVE_ORACLE_TOPIC_EXAMPLES,
    texts=_reflection_texts(
        welcome=(
            "Что в отношениях сейчас не даёт покоя? Globa разберёт динамику, ваши границы "
            "и возможные следующие шаги — без попыток угадывать чужие мысли."
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
    topic_examples=MYSTICAL_PSYCHOLOGIST_TOPIC_EXAMPLES,
    texts=_reflection_texts(
        welcome=(
            "Какую ситуацию хотите увидеть со стороны? Разберём повторяющийся сценарий, "
            "внутренний конфликт или выбор через метафоры и архетипы.\n\n"
            "Это не заменяет терапию."
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
