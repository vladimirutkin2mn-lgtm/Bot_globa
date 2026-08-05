"""Strict structured output contract for oracle readings."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.reading import ReadingSymbolInput, SymbolOrientation

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
SymbolCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"),
]
PositionCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"),
]


class StrictReadingResultModel(BaseModel):
    """Closed JSON objects with strict scalar types."""

    model_config = ConfigDict(extra="forbid", strict=True)


class SafetyCategory(StrEnum):
    SELF_HARM = "self_harm"
    VIOLENCE_OR_STALKING = "violence_or_stalking"
    MEDICAL = "medical"
    LEGAL = "legal"
    FINANCIAL_OR_GAMBLING = "financial_or_gambling"
    GUARANTEED_FUTURE = "guaranteed_future"
    THIRD_PARTY_MIND_READING = "third_party_mind_reading"
    FEAR_BASED_UPSELL = "fear_based_upsell"
    DEPENDENCY = "dependency"


class ReadingSymbolResult(StrictReadingResultModel):
    symbol_id: SymbolCode
    position: PositionCode
    orientation: SymbolOrientation
    interpretation: Text


class ReadingScenario(StrictReadingResultModel):
    scenario: Text
    conditions: list[ShortText] = Field(min_length=1, max_length=5)


class ShareCardPayload(StrictReadingResultModel):
    headline: ShortText
    short_text: ShortText


class ReadingSafetyAssessment(StrictReadingResultModel):
    high_risk_detected: bool
    categories: list[SafetyCategory] = Field(max_length=10)


class ReadingResult(StrictReadingResultModel):
    title: ShortText
    opening: Text
    symbols: list[ReadingSymbolResult] = Field(max_length=12)
    patterns: list[Text] = Field(max_length=7)
    possible_scenarios: list[ReadingScenario] = Field(min_length=1, max_length=5)
    reflection_questions: list[Text] = Field(max_length=5)
    practical_step: Text
    uncertainty_note: Text
    share_card: ShareCardPayload
    safety: ReadingSafetyAssessment


class ReadingSemanticValidationError(ValueError):
    """Safe semantic error with field locations and no generated/private text."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(";".join(issues))


def validate_reading_semantics(
    result: ReadingResult,
    expected_symbols: list[ReadingSymbolInput],
) -> None:
    """Ensure the model explains exactly the symbols chosen by the application."""

    issues: list[str] = []
    expected_by_position = {symbol.position: symbol for symbol in expected_symbols}
    if len(expected_by_position) != len(expected_symbols):
        raise ValueError("expected reading symbols contain duplicate positions")
    result_positions = [symbol.position for symbol in result.symbols]
    if len(result_positions) != len(set(result_positions)):
        issues.append("symbols:duplicate_position")
    if len(result.symbols) != len(expected_symbols):
        issues.append("symbols:count_mismatch")
    for index, symbol in enumerate(result.symbols):
        expected = expected_by_position.get(symbol.position)
        if expected is None:
            issues.append(f"symbols.{index}.position:unexpected")
            continue
        if symbol.symbol_id != expected.symbol_id:
            issues.append(f"symbols.{index}.symbol_id:mismatch")
        if symbol.orientation is not expected.orientation:
            issues.append(f"symbols.{index}.orientation:mismatch")
    missing_positions = set(expected_by_position).difference(result_positions)
    if missing_positions:
        issues.append("symbols:missing_position")
    if result.safety.high_risk_detected != bool(result.safety.categories):
        issues.append("safety:inconsistent_risk_flag")
    if issues:
        raise ReadingSemanticValidationError(issues)
