"""Versioned product-owned Tarot spreads built on the RWS card tradition.

A. E. Waite documented general divination methods, including the Celtic method, but did
not define canonical modern spreads for product topics such as love, work or repeating
patterns. These layouts are therefore explicitly application-owned. They specialize the
questions assigned to positions while card meanings remain grounded in `rws-78-v1`.
"""

from app.domain.tarot import (
    ONE_CARD_SPREAD,
    THREE_CARD_SPREAD,
    TarotCard,
    TarotSpread,
    card_knowledge,
)

RELATIONSHIP_FIVE_V1 = TarotSpread(
    code="relationship_five_v1",
    positions=(
        "relationship_dynamic",
        "bond_or_attraction",
        "distance_or_friction",
        "unspoken_factor",
        "relationship_direction",
    ),
)

WORK_FIVE_V1 = TarotSpread(
    code="work_five_v1",
    positions=(
        "work_situation",
        "opportunity",
        "constraint",
        "available_resource",
        "work_next_step",
    ),
)

DECISION_FIVE_V1 = TarotSpread(
    code="decision_five_v1",
    positions=(
        "decision_core",
        "option_a_potential",
        "option_a_cost",
        "option_b_potential",
        "option_b_cost",
    ),
)

PATTERN_FIVE_V1 = TarotSpread(
    code="pattern_five_v1",
    positions=(
        "pattern_trigger",
        "pattern_hidden_need",
        "pattern_reinforcement",
        "pattern_break_point",
        "pattern_new_response",
    ),
)

OPEN_QUESTION_FIVE_V1 = TarotSpread(
    code="open_question_five_v1",
    positions=(
        "central_theme",
        "emerging_influence",
        "fading_influence",
        "blind_spot",
        "near_term_direction",
    ),
)

TOPIC_SPREADS: dict[str, TarotSpread] = {
    "love": RELATIONSHIP_FIVE_V1,
    "work": WORK_FIVE_V1,
    "decision": DECISION_FIVE_V1,
    "repeating_pattern": PATTERN_FIVE_V1,
    "general_forecast": OPEN_QUESTION_FIVE_V1,
}

_SPREADS: dict[str, TarotSpread] = {
    ONE_CARD_SPREAD.code: ONE_CARD_SPREAD,
    THREE_CARD_SPREAD.code: THREE_CARD_SPREAD,
    **{spread.code: spread for spread in TOPIC_SPREADS.values()},
}

POSITION_FOCUS: dict[str, str] = {
    "relationship_dynamic": "что реально формирует динамику отношений сейчас",
    "bond_or_attraction": "что поддерживает притяжение, интерес или чувство связи",
    "distance_or_friction": "что создаёт дистанцию, напряжение или несовпадение",
    "unspoken_factor": "какой неочевидный фактор влияет на контакт без утверждений о чужих мыслях",
    "relationship_direction": "куда может двигаться связь при сохранении текущих условий",
    "work_situation": "что сильнее всего определяет рабочую или материальную ситуацию сейчас",
    "opportunity": "какая возможность или пространство для роста доступно в ситуации",
    "constraint": "какое ограничение, риск или узкое место важно учитывать",
    "available_resource": "на какой навык, ресурс или опору пользователь реально может опереться",
    "work_next_step": "какой следующий низкорисковый рабочий шаг поддерживает позицию пользователя",
    "decision_core": (
        "в чём находится настоящая развилка выбора, а не только его внешняя формулировка"
    ),
    "option_a_potential": "что может дать первый путь или вариант при его выборе",
    "option_a_cost": "какую цену, компромисс или ограничение несёт первый путь",
    "option_b_potential": "что может дать второй путь или вариант при его выборе",
    "option_b_cost": "какую цену, компромисс или ограничение несёт второй путь",
    "pattern_trigger": "что обычно запускает повторяющийся сценарий",
    "pattern_hidden_need": (
        "какая потребность или мотив может удерживать сценарий без клинических утверждений"
    ),
    "pattern_reinforcement": "что подпитывает повторение после запуска",
    "pattern_break_point": "в какой точке появляется реальная возможность прервать цикл",
    "pattern_new_response": "какая альтернативная реакция может изменить дальнейшую динамику",
    "central_theme": "главная тема конкретного вопроса пользователя сейчас",
    "emerging_influence": "что начинает проявляться сильнее и требует внимания",
    "fading_influence": "что постепенно теряет влияние или подходит к завершению",
    "blind_spot": "что пользователь может недооценивать или не замечать в текущей картине",
    "near_term_direction": (
        "какой вектор может стать заметнее при сохранении текущих условий, без обещания будущего"
    ),
}


def tarot_spread(code: str) -> TarotSpread | None:
    """Resolve both legacy layouts and the current topic-specific layouts by stable code."""

    return _SPREADS.get(code)


def spread_for_topic(topic: str) -> TarotSpread | None:
    """Return the versioned product spread selected when a new Tarot draft is created."""

    return TOPIC_SPREADS.get(topic)


def card_knowledge_for_position(card: TarotCard, position: str, *, reversed: bool) -> str:
    """Enrich RWS card knowledge with the application-owned meaning of this spread position."""

    knowledge = card_knowledge(card, position, reversed=reversed)
    focus = POSITION_FOCUS.get(position)
    if focus is None:
        return knowledge
    return knowledge.replace(f"position_focus={position}", f"position_focus={focus}", 1)
