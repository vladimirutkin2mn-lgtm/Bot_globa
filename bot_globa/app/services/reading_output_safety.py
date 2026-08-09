"""Deterministic safety checks for user-visible oracle output."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum

from app.domain.reading_result import ReadingResult


class ReadingOutputSafetyCategory(StrEnum):
    """Internal categories independent from the model-declared safety field."""

    SELF_HARM = "self_harm"
    VIOLENCE_OR_STALKING = "violence_or_stalking"
    MEDICAL_CLAIM = "medical_claim"
    LEGAL_DIRECTION = "legal_direction"
    FINANCIAL_OR_GAMBLING = "financial_or_gambling"
    GUARANTEED_FUTURE = "guaranteed_future"
    EXACT_DATE_PREDICTION = "exact_date_prediction"
    THIRD_PARTY_MIND_READING = "third_party_mind_reading"
    INFIDELITY_OR_CRIME_CLAIM = "infidelity_or_crime_claim"
    DEATH_CLAIM = "death_claim"
    CURSE_CLAIM = "curse_claim"
    FEAR_BASED_UPSELL = "fear_based_upsell"
    DEPENDENCY = "dependency"


class ReadingOutputSafetyError(ValueError):
    """Safe output error containing only field paths and category codes."""

    def __init__(self, issues: tuple[str, ...]) -> None:
        self.issues = issues
        super().__init__("unsafe_output")


@dataclass(frozen=True, slots=True)
class _SafetyRule:
    category: ReadingOutputSafetyCategory
    patterns: tuple[re.Pattern[str], ...]


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value) for value in values)


_RULES: tuple[_SafetyRule, ...] = (
    _SafetyRule(
        ReadingOutputSafetyCategory.SELF_HARM,
        _patterns(
            r"\b(?:kill yourself|end your life|you should die)\b",
            r"\b(?:убей себя|покончи с собой|тебе лучше умереть)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.VIOLENCE_OR_STALKING,
        _patterns(
            r"\b(?:stalk|track|follow) (?:him|her|them) "
            r"without (?:consent|his knowledge|her knowledge|their knowledge)\b",
            r"\b(?:hurt|attack|kill) (?:him|her|them)\b",
            r"\b(?:выследи|преследуй|следи за) (?:ним|ней|ними) "
            r"(?:тайно|без согласия|без ведома)\b",
            r"\b(?:причини вред|напади на|убей) (?:его|ее|их)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.MEDICAL_CLAIM,
        _patterns(
            r"\byou (?:have|are diagnosed with) "
            r"(?:cancer|a tumor|bipolar disorder|depression)\b",
            r"\byou are pregnant\b",
            r"\bstop taking (?:your )?(?:medication|medicine|pills)\b",
            r"\bу (?:вас|тебя) "
            r"(?:рак|опухоль|биполярное расстройство|депрессия)\b",
            r"\b(?:вы|ты) беременн(?:ы|а)\b",
            r"\bперестан(?:ьте|ь) принимать (?:лекарство|таблетки)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.LEGAL_DIRECTION,
        _patterns(
            r"\byou will (?:win|lose) (?:the )?(?:case|court case|trial|lawsuit)\b",
            r"\btell the (?:judge|court) (?:that|to)\b",
            r"\bhide from (?:the )?police\b",
            r"\b(?:вы|ты) "
            r"(?:выиграете|выиграешь|проиграете|проиграешь) суд\b",
            r"\bскаж(?:ите|и) (?:судье|в суде),? (?:что|чтобы)\b",
            r"\bскрой(?:тесь|ся) от полиции\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.FINANCIAL_OR_GAMBLING,
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
        ReadingOutputSafetyCategory.GUARANTEED_FUTURE,
        _patterns(
            r"\b(?:will definitely|will certainly|is guaranteed to)\b",
            r"\b(?:this|it|he|she|they) will "
            r"(?:happen|return|come back|marry|win)\b",
            r"\b(?:он|она|они|это)?\s*"
            r"(?:точно|гарантированно|обязательно)\s+"
            r"(?:вернется|произойдет|случится|будет)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.EXACT_DATE_PREDICTION,
        _patterns(
            r"\b(?:will happen|will return|will come back) on "
            r"(?:\d{1,2}|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"january|february|march|april|may|june|july|august|september|october|"
            r"november|december)\b",
            r"\b(?:вернется|произойдет|случится) "
            r"(?:\d{1,2} \w+|в (?:понедельник|вторник|среду|четверг|пятницу|"
            r"субботу|воскресенье))\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.THIRD_PARTY_MIND_READING,
        _patterns(
            r"\b(?:i know|the cards know) (?:exactly )?what "
            r"(?:he|she|they) (?:thinks?|feels?)\b",
            r"\b(?:he|she|they) (?:secretly|definitely|certainly) "
            r"(?:thinks?|feels?|loves?|wants?)\b",
            r"\b(?:я|карты) (?:точно )?зна(?:ю|ют),? что "
            r"(?:он|она|они) (?:думает|думают|чувствует|чувствуют)\b",
            r"\b(?:он|она|они) (?:тайно|точно|определенно) "
            r"(?:думает|думают|чувствует|чувствуют|любит|любят|хочет|хотят)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.INFIDELITY_OR_CRIME_CLAIM,
        _patterns(
            r"\b(?:he|she|they) (?:is|are) cheating on you\b",
            r"\b(?:he|she|they) committed (?:a crime|fraud|the theft)\b",
            r"\b(?:он|она) (?:изменяет|изменила|изменил) (?:вам|тебе)\b",
            r"\b(?:он|она|они) совершил(?:а|и)? "
            r"(?:преступление|мошенничество|кражу)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.DEATH_CLAIM,
        _patterns(
            r"\b(?:you|he|she|they) will die\b",
            r"\b(?:ты|вы|он|она|они) (?:умрешь|умрете|умрет|умрут)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.CURSE_CLAIM,
        _patterns(
            r"\b(?:you are|he is|she is|they are) cursed\b",
            r"\bthere is (?:a curse|dark energy) on you\b",
            r"\bна (?:вас|тебе|нем|ней) (?:порча|проклятие)\b",
            r"\b(?:вас|тебя|его|ее) прокляли\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.FEAR_BASED_UPSELL,
        _patterns(
            r"\b(?:curse|cursed|dark energy)\b.{0,120}\b(?:pay|buy|purchase)\b",
            r"\b(?:pay|buy|purchase)\b.{0,120}\b"
            r"(?:or something bad|before it is too late|remove the curse)\b",
            r"\b(?:порча|проклятие|темная энергия)\b.{0,120}\b"
            r"(?:оплати|купите|купи|закажи)\b",
            r"\b(?:оплати|купите|купи|закажи)\b.{0,120}\b"
            r"(?:иначе случится беда|пока не поздно|снять порчу)\b",
        ),
    ),
    _SafetyRule(
        ReadingOutputSafetyCategory.DEPENDENCY,
        _patterns(
            r"\b(?:ask|consult) (?:the cards|me) every day\b",
            r"\bdo not (?:decide|act|make decisions) "
            r"without (?:a|another|the) reading\b",
            r"\b(?:спрашивай|спрашивайте|проверяй|проверяйте) "
            r"(?:карты|расклад) каждый день\b",
            r"\bне принимай(?:те)? решени(?:е|я) "
            r"без (?:нового |еще одного )?расклада\b",
        ),
    ),
)


class ReadingOutputSafetyValidator:
    """Reject unsafe claims before a structured reading can be persisted."""

    max_issues = 20

    def validate(self, result: ReadingResult) -> None:
        self.validate_texts(self._visible_texts(result))

    def validate_texts(self, values: Iterable[tuple[str, str]]) -> None:
        """Validate arbitrary user-visible fields with the same production rules."""

        issues: list[str] = []
        for path, value in values:
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
