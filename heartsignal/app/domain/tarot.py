"""Versioned tarot catalog and spread definitions for deterministic readings."""

# ruff: noqa: RUF001

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TarotCard:
    code: str
    name_ru: str
    upright_theme: str
    reversed_theme: str


@dataclass(frozen=True, slots=True)
class TarotSpread:
    code: str
    positions: tuple[str, ...]
    allow_reversed: bool = True


@dataclass(frozen=True, slots=True)
class TarotCatalog:
    version: str
    cards: tuple[TarotCard, ...]

    def __post_init__(self) -> None:
        codes = [card.code for card in self.cards]
        if not self.version:
            raise ValueError("tarot catalog version is required")
        if not cards_are_unique(codes):
            raise ValueError("tarot card codes must be unique")


def cards_are_unique(codes: list[str]) -> bool:
    return len(codes) == len(set(codes))


MAJOR_ARCANA_V1 = TarotCatalog(
    version="tarot-major-v1",
    cards=(
        TarotCard("major_00", "Шут", "новое начало и свобода", "импульсивность и бегство"),
        TarotCard("major_01", "Маг", "инициатива и мастерство", "манипуляция и рассеянность"),
        TarotCard(
            "major_02", "Верховная Жрица", "интуиция и скрытое знание", "подавленная интуиция"
        ),
        TarotCard("major_03", "Императрица", "рост и забота", "истощение и избыточная опека"),
        TarotCard("major_04", "Император", "структура и ответственность", "жёсткость и контроль"),
        TarotCard("major_05", "Иерофант", "ценности и традиция", "догматизм и чужие правила"),
        TarotCard(
            "major_06", "Влюблённые", "выбор и согласование ценностей", "разрыв между желаниями"
        ),
        TarotCard("major_07", "Колесница", "направленное движение", "потеря курса и давление"),
        TarotCard("major_08", "Сила", "мягкая стойкость", "сомнение в себе и подавление"),
        TarotCard("major_09", "Отшельник", "внутренний поиск", "изоляция и избегание"),
        TarotCard("major_10", "Колесо Фортуны", "смена цикла", "сопротивление переменам"),
        TarotCard(
            "major_11", "Справедливость", "последствия и честный баланс", "самообман и перекос"
        ),
        TarotCard("major_12", "Повешенный", "новый взгляд и пауза", "застой без переосмысления"),
        TarotCard("major_13", "Смерть", "завершение и трансформация", "удерживание отжившего"),
        TarotCard("major_14", "Умеренность", "интеграция и мера", "крайности и нетерпение"),
        TarotCard(
            "major_15", "Дьявол", "привязанность и теневая мотивация", "освобождение от зависимости"
        ),
        TarotCard("major_16", "Башня", "разрушение ложной опоры", "страх необходимого изменения"),
        TarotCard(
            "major_17", "Звезда", "надежда и восстановление", "разочарование и потеря ориентиров"
        ),
        TarotCard("major_18", "Луна", "неопределённость и воображение", "прояснение иллюзий"),
        TarotCard("major_19", "Солнце", "ясность и жизненность", "временная закрытость радости"),
        TarotCard("major_20", "Суд", "переоценка и призвание", "избегание ответственности"),
        TarotCard("major_21", "Мир", "завершённость и интеграция", "незавершённый цикл"),
    ),
)

THREE_CARD_SPREAD = TarotSpread(
    code="three_card_v1",
    positions=("current_influence", "hidden_factor", "next_step"),
)

ONE_CARD_SPREAD = TarotSpread(
    code="one_card_v1",
    positions=("main_theme",),
)

_SPREADS = {
    ONE_CARD_SPREAD.code: ONE_CARD_SPREAD,
    THREE_CARD_SPREAD.code: THREE_CARD_SPREAD,
}


def tarot_spread(code: str) -> TarotSpread | None:
    return _SPREADS.get(code)
