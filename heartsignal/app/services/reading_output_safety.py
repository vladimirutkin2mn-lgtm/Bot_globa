# ruff: noqa: RUF001
"""Deterministic safety checks for user-visible oracle output."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from app.domain.reading_result import ReadingResult, SafetyCategory


class ReadingOutputSafetyError(ValueError):
    """Safe output error containing only field paths and category codes."""

    def __init__(self, issues: tuple[str, ...]) -> None:
        self.issues = issues
        super().__init__("unsafe_output")


@dataclass(frozen=True, slots=True)
class _SafetyRule:
    category: SafetyCategory
    patterns: tuple[re.Pattern[str], ...]


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value) for value in values)


_RULES: tuple[_SafetyRule, ...] = (
    _SafetyRule(
        SafetyCategory.SELF_HARM,
        _patterns(
            r"\b(?:kill yourself|end your life|you should die)\b",
            r"\b(?:убей себя|покончи с собой|тебе лучше умереть)\b",
        ),
    ),
    _SafetyRule(
        SafetyCategory.VIOLENCE_OR_STALKING,
        _patterns(
            r"\b(?:stalk|track|follow) (?:him|her|them) without (?:consent|their knowledge)\b",
            r"\b(?:hurt|attack|kill) (?:him|her|them)\b",
            r"\b(?:выследи|преследуй|следи за) (?:ним|ней|ними) (?:тайно|без согласия|без ведома)\b",  # noqa: E501
            r"\b(?:причини вред|напади на|убей) (?:его|ее|их)\b",
        ),
    ),
    _SafetyRule(
        SafetyCategory.MEDICAL,
        _patterns(
            r"\byou (?:have|are diagnosed with) (?:cancer|a tumor|bipolar disorder|depression)\b",
            r"\byou are pregnant\b",
            r"\bstop taking (?:your )?(?:medication|medicine|pills)\b",
            r"\bу (?:вас|тебя) (?:рак|опухоль|биполярное расстройство|депрессия)\b",
            r"\b(?:вы|ты) беременн(?:ы|а)\b",
            r"\bперестан(?:ьте|ь) принимать (?:лекарство|таблетки)\b",
        ),
    ),
    _SafetyRule(
        SafetyCategory.LEGAL,
        _patterns(
            r"\byou will (?:win|lose) (?:the )?(?:case|trial|lawsuit)\b",
            r"\btell the (?:judge|court) (?:that|to)\b",
            r"\bhide from (?:the )?police\b",
            r"\b(?:вы|ты) (?:выиграете|выиграешь|проиграете|проиграешь) суд\b",
            r"\bскаж(?:ите|и) (?:судье|в суде),? (?:что|чтобы)\b",
            r"\bскрой(?:тесь|ся) от полиции\b",
        ),
    ),
    _SafetyRule(
        SafetyCategory.FINANCIAL_OR_GAMBLING,
        _patterns(
            r"\binvest all (?:your|the) money\b",
            r"\btake out (?:a|the) loan\b",
            r"\bbet all (?:your|the) money\b",
            r"\bbuy (?:this|that) stock\b",
            r"\bвложи(?:те)? все деньги\b",
            r"\b(?:возьми|берите|возьмите) кредит\b",
            r"\bпостав(?:ь|ьте) все деньги\b",
            r"\bкупи(?:те)? (?:эту|данную) акцию\b",
        ),
    ),
    _SafetyRule(
        SafetyCategory.GUARANTEED_FUTURE,
        _patterns(
            r"\b(?:will definitely|will certainly|is guaranteed to)\b",
            r"\b(?:will happen|will return|will come back) on (?:\d{1,2}|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b",  # noqa: E501
            r"\b(?:он|она|они|это)?\s*(?:точно|гарантированно|обязательно)\s+(?:вернется|произойдет|случится|будет)\b",
            r"\b(?:вернется|произойдет|случится) (?:\d{1,2} \w+|в (?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))\b",  # noqa: E501
        ),
    ),
    _SafetyRule(
        SafetyCategory.THIRD_PARTY_MIND_READING,
        _patterns(
            r"\b(?:i know|the cards know) (?:exactly )?what (?:he|she|they) (?:thinks?|feels?)\b",
            r"\b(?:he|she|they) (?:secretly|definitely|certainly) (?:thinks?|feels?|loves?|wants?)\b",  # noqa: E501
            r"\b(?:я|карты) (?:точно )?зна(?:ю|ют),? что (?:он|она|они) (?:думает|думают|чувствует|чувствуют)\b",  # noqa: E501
            r"\b(?:он|она|они) (?:тайно|точно|определенно) (?:думает|думают|чувствует|чувствуют|любит|любят|хочет|хотят)\b",  # noqa: E501
        ),
    ),
    _SafetyRule(
        SafetyCategory.FEAR_BASED_UPSELL,
        _patterns(
            r"\b(?:curse|cursed|dark energy)\b.{0,120}\b(?:pay|buy|purchase)\b",
            r"\b(?:pay|buy|purchase)\b.{0,120}\b(?:or something bad|before it is too late|remove the curse)\b",  # noqa: E501
            r"\b(?:порча|проклятие|темная энергия)\b.{0,120}\b(?:оплати|купите|купи|закажи)\b",
            r"\b(?:оплати|купите|купи|закажи)\b.{0,120}\b(?:иначе случится беда|пока не поздно|снять порчу)\b",  # noqa: E501
        ),
    ),
    _SafetyRule(
        SafetyCategory.DEPENDENCY,
        _patterns(
            r"\b(?:ask|consult) (?:the cards|me) every day\b",
            r"\bdo not (?:decide|act|make decisions) without (?:a|another|the) reading\b",
            r"\b(?:спрашивай|спрашивайте|проверяй|проверяйте) (?:карты|расклад) каждый день\b",
            r"\bне принимай(?:те)? решени(?:е|я) без (?:нового |еще одного )?расклада\b",
        ),
    ),
)


class ReadingOutputSafetyValidator:
    """Reject unsafe claims before a structured reading can be persisted."""

    max_issues = 20

    def validate(self, result: ReadingResult) -> None:
        issues: list[str] = []
        for path, value in self._visible_texts(result):
            normalized = self._normalize(value)
            for rule in _RULES:
                if any(pattern.search(normalized) for pattern in rule.patterns):
                    issues.append(f"output.{path}:{rule.category.value}")
                    if len(issues) >= self.max_issues:
                        raise ReadingOutputSafetyError(tuple(dict.fromkeys(issues)))
        unique = tuple(dict.fromkeys(issues))
        if unique:
            raise ReadingOutputSafetyError(unique)

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()

    @staticmethod
    def _visible_texts(result: ReadingResult) -> Iterator[tuple[str, str]]:
        yield "title", result.title
        yield "opening", result.opening
        for index, symbol in enumerate(result.symbols):
            yield f"symbols.{index}.interpretation", symbol.interpretation
        for index, pattern in enumerate(result.patterns):
            yield f"patterns.{index}", pattern
        for scenario_index, scenario in enumerate(result.possible_scenarios):
            yield f"possible_scenarios.{scenario_index}.scenario", scenario.scenario
            for condition_index, condition in enumerate(scenario.conditions):
                yield (
                    f"possible_scenarios.{scenario_index}.conditions.{condition_index}",
                    condition,
                )
        for index, question in enumerate(result.reflection_questions):
            yield f"reflection_questions.{index}", question
        yield "practical_step", result.practical_step
        yield "uncertainty_note", result.uncertainty_note
        yield "share_card.headline", result.share_card.headline
        yield "share_card.short_text", result.share_card.short_text
