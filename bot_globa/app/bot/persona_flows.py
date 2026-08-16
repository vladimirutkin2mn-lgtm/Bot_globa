"""The MVP reading flows: namespace, topics and Russian copy for each persona."""

from types import MappingProxyType

from app.bot.conversion_hooks import ConversionHookCopy
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
        "love": "мы стали реже общаться; что показывают карты о динамике между нами",
        "work": "выбираю между текущей работой и новым предложением; что я могу не замечать",
        "decision": "у меня два варианта; что карты подсвечивают в каждом из них",
        "repeating_pattern": "я снова откладываю важное решение; что стоит за этим сценарием",
        "general_forecast": "какая тема сейчас сильнее всего проявляется в моей жизни",
    }
)

LOVE_ORACLE_TOPIC_LABELS = MappingProxyType(
    {
        "love": "Что он/она чувствует",
        "communication": "Стоит ли проявиться",
        "choice": "Куда всё движется",
        "repeating_pattern": "Почему всё повторяется",
        "boundaries": "Свой вопрос",
    }
)
LOVE_ORACLE_TOPIC_EXAMPLES = MappingProxyType(
    {
        "love": "что сейчас между мной и Арсением — есть ли с его стороны чувства",
        "communication": "мы давно не общались; стоит ли мне написать первой",
        "choice": "между нами всё неопределённо; куда может двигаться эта история",
        "repeating_pattern": "почему он снова сближается со мной, а потом отдаляется",
        "boundaries": "что мне важно увидеть в этих отношениях прямо сейчас",
    }
)

MYSTICAL_PSYCHOLOGIST_TOPIC_LABELS = MappingProxyType(
    {
        "repeating_pattern": "Повторяющийся сценарий",
        "decision": "Внутренний конфликт",
        "work": "Работа",
        "love": "Отношения",
        "self_reflection": "Свой вопрос",
    }
)
MYSTICAL_PSYCHOLOGIST_TOPIC_EXAMPLES = MappingProxyType(
    {
        "repeating_pattern": "я берусь за новое, но отступаю перед первым заметным результатом",
        "decision": "одна часть меня хочет перемен, другая держится за безопасность",
        "work": "после рабочих встреч долго прокручиваю в голове каждое своё слово",
        "love": "почему я молчу о важном, пока напряжение не становится слишком сильным",
        "self_reflection": "какая внутренняя роль сейчас сильнее всего управляет моими решениями",
    }
)


def _tarot_hook(unlock_lines: tuple[str, ...]) -> ConversionHookCopy:
    return ConversionHookCopy(
        branch_title="Карты дают не один исход — здесь есть развилка.",
        single_title="Одна линия уже проявилась, но её условия важнее самого исхода.",
        scenario_prefix="Один из сценариев, который показывает расклад:",
        hidden_conditions_line=(
            "Короткая версия не раскрывает, какие карты и условия усиливают именно эту линию."
        ),
        alternative_line="Есть и другая линия — она становится сильнее при другой связке условий.",
        unlock_title="В полном раскладе откроется:",
        unlock_lines=unlock_lines,
    )


TAROT_DEFAULT_HOOK = _tarot_hook(
    (
        "как карты связаны между собой и где находится главная развилка",
        "что усиливает каждый возможный сценарий",
        "какой следующий шаг лучше всего поддерживает вашу позицию",
    )
)
TAROT_SPREAD_HOOKS: tuple[tuple[str, ConversionHookCopy], ...] = (
    (
        "relationship_five_v1",
        _tarot_hook(
            (
                "что поддерживает связь, а что создаёт дистанцию",
                "какой скрытый фактор меняет динамику между вами",
                "куда ведёт текущая линия, если ничего не менять",
            )
        ),
    ),
    (
        "work_five_v1",
        _tarot_hook(
            (
                "где в ситуации реальная возможность, а где ограничение",
                "на какой ресурс сейчас можно опереться",
                "какой следующий шаг сильнее меняет рабочую или денежную ситуацию",
            )
        ),
    ),
    (
        "decision_five_v1",
        _tarot_hook(
            (
                "что даёт вариант A и какой у него скрытый обмен",
                "что даёт вариант B и чем он обходится",
                "какой фактор важнее самого выбора между A и B",
            )
        ),
    ),
    (
        "pattern_five_v1",
        _tarot_hook(
            (
                "что запускает повторяющийся цикл и что его подпитывает",
                "где находится точка, в которой сценарий можно разорвать",
                "какая новая реакция действительно меняет привычную траекторию",
            )
        ),
    ),
    (
        "open_question_five_v1",
        _tarot_hook(
            (
                "что сейчас усиливается, а что постепенно уходит",
                "где находится слепая зона вопроса",
                "какое ближайшее направление складывается из всего расклада",
            )
        ),
    ),
)

LOVE_ORACLE_HOOK = ConversionHookCopy(
    branch_title="В этой динамике есть развилка — и она зависит не от одной детали.",
    single_title="Одна траектория уже видна, но решают условия, при которых она сохраняется.",
    scenario_prefix="Один из возможных сценариев между вами:",
    hidden_conditions_line=(
        "Короткая версия не раскрывает, какие наблюдаемые действия ведут именно к нему."
    ),
    alternative_line="Есть и другая траектория — она включается при другой динамике общения.",
    unlock_title="В полном разборе я покажу:",
    unlock_lines=(
        "что сейчас создаёт притяжение, а что увеличивает дистанцию",
        "какая динамика видна по действиям и взаимодействию, без чтения чужих мыслей",
        "что в вашей зоне влияния способно изменить траекторию этой связи",
    ),
)

MYSTICAL_PSYCHOLOGIST_HOOK = ConversionHookCopy(
    branch_title="У этого сценария есть точка переключения — и она не там, где обычно её ищут.",
    single_title="Сценарий уже виден; теперь важнее понять, что именно удерживает его на месте.",
    scenario_prefix="Один из возможных вариантов развития:",
    hidden_conditions_line=(
        "Короткая версия не раскрывает условия, которые поддерживают или ослабляют этот паттерн."
    ),
    alternative_line="Есть и альтернативная траектория — она появляется при другой реакции на триггер.",
    unlock_title="В полном разборе станет видно:",
    unlock_lines=(
        "какая внутренняя роль запускает или удерживает этот сценарий",
        "где находится проверяемая точка разрыва привычного цикла",
        "каким маленьким экспериментом можно проверить интерпретацию на практике",
    ),
)


def _reflection_texts(*, welcome: str, unavailable: str) -> PersonaFlowTexts:
    return PersonaFlowTexts(
        welcome=welcome,
        processing="Вопрос принят. Собираю разбор — обычно это занимает до 30 секунд.",
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
    )


TAROT_FLOW = PersonaFlow(
    persona_code="tarot_reader",
    namespace="tarot",
    states=TarotStates,
    topic_labels=TAROT_TOPIC_LABELS,
    topic_examples=TAROT_TOPIC_EXAMPLES,
    texts=PersonaFlowTexts(
        welcome=(
            "🔮 Таролог\n\n"
            "Задайте вопрос — карты уже через несколько мгновений сложатся в один расклад. "
            "Я покажу, что в ситуации видно сейчас, что остаётся в тени и куда может вести "
            "каждый из возможных ходов.\n\nЭто развлекательная практика для рефлексии."
        ),
        processing="Вопрос принят. Фиксирую карты и собираю расклад…",
        opening="Открываю сохранённый расклад…",
        already_processing="Этот расклад уже обрабатывается. Откройте его немного позже.",
        unavailable="Таролог временно недоступен. Начните новый расклад позже.",
        failed="Не удалось завершить интерпретацию. Карты сохранены, поэтому попытку можно повторить.",
        history_title="Ваши последние готовые расклады:",
        history_empty="Готовых раскладов пока нет.",
        history_fallback="Расклад",
        locked="Расклад готов. Откройте полный разбор за {price}.",
        unlock_failed="Не удалось открыть полный расклад. Списание отменено или возвращено.",
        unlock_button="Открыть полный разбор — {price}",
        new_button="Новый расклад",
    ),
    copy=ReadingCopy(
        emoji="🔮",
        full_title_prefix="Полный расклад",
        drawn_symbols_title="Ваш расклад:",
        result_symbols_title="Что говорит каждая карта:",
        main_theme_title="Что показывает расклад",
        practical_step_title="Что сделать с этим знанием",
        uncertainty_title="Граница расклада",
        patterns_title="Как карты связаны между собой",
        scenarios_title="Куда может повернуть ситуация",
        reflection_title="На что стоит ответить себе",
        hook=TAROT_DEFAULT_HOOK,
        hook_by_symbol_set=TAROT_SPREAD_HOOKS,
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
            "💞 Любовный оракул\n\n"
            "Спросите о человеке или ваших отношениях. Я посмотрю на притяжение, дистанцию, "
            "недосказанность, инициативу и то, куда может двигаться эта история."
        ),
        unavailable="Любовный оракул временно недоступен. Начните новый разбор позже.",
    ),
    copy=ReadingCopy(
        emoji="💞",
        full_title_prefix="Любовный разбор",
        drawn_symbols_title="Опоры разбора:",
        result_symbols_title="Разбор по частям:",
        main_theme_title="Что между вами сейчас",
        practical_step_title="Что делать вам",
        uncertainty_title="Что важно помнить",
        patterns_title="Что влияет на эту связь",
        scenarios_title="Как может развиваться эта история",
        reflection_title="Что стоит спросить себя",
        hook=LOVE_ORACLE_HOOK,
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
            "🌙 Мистический психолог\n\n"
            "Опишите ситуацию, которая будто возвращается по кругу. Я попробую увидеть в ней "
            "внутренний конфликт, повторяющуюся роль или архетип — как метафору, а не диагноз.\n\n"
            "Это не заменяет терапию."
        ),
        unavailable="Мистический психолог временно недоступен. Начните новый разбор позже.",
    ),
    copy=ReadingCopy(
        emoji="🌙",
        full_title_prefix="Разбор внутреннего сценария",
        drawn_symbols_title="Опоры рефлексии:",
        result_symbols_title="Разбор по частям:",
        main_theme_title="Какой сценарий здесь виден",
        practical_step_title="Маленький эксперимент",
        uncertainty_title="Граница интерпретации",
        patterns_title="Какие роли здесь сталкиваются",
        scenarios_title="Как сценарий меняется при разных условиях",
        reflection_title="Вопросы, которые могут открыть слепую зону",
        hook=MYSTICAL_PSYCHOLOGIST_HOOK,
    ),
)

MVP_READING_FLOWS: tuple[PersonaFlow, ...] = (
    TAROT_FLOW,
    LOVE_ORACLE_FLOW,
    MYSTICAL_PSYCHOLOGIST_FLOW,
)
