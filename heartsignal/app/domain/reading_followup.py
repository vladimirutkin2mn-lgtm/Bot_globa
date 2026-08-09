"""Strict follow-up contract grounded in an already paid reading.

The answer may only cite sections that exist in the reading the user paid for. That is
what stops a follow-up from becoming a second, ungrounded reading — the model explains
what was already produced instead of generating new material.

Both result schemas are supported: the shared `reading-result-v1` and the astrologer's
`astrology-reading-result-v1`. Their sections overlap but are not identical, so the
allowed references are derived from the actual result rather than from a fixed list.
"""

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.horoscope import AstrologyReadingResult
from app.domain.reading_result import ReadingResult, ReadingSafetyAssessment

ReadingFollowUpResult = ReadingResult | AstrologyReadingResult

_REFERENCE_PATTERN = (
    r"(title|opening|overview|practical_step|uncertainty_note|safety|"
    r"symbols\.[0-9]+|patterns\.[0-9]+|interpretations\.[0-9]+|themes\.[0-9]+|"
    r"possible_scenarios\.[0-9]+|reflection_questions\.[0-9]+)"
)

QuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
AnswerText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2500),
]
LimitationText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
ReadingRef = Annotated[
    str,
    StringConstraints(pattern=rf"^{_REFERENCE_PATTERN}$", max_length=32),
]


class StrictModel(BaseModel):
    """Closed object model; JSON scalar types remain naturally deserializable."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ReadingFollowUpQuestionInput(StrictModel):
    question: QuestionText


class ReadingFollowUpAnswer(StrictModel):
    answer: AnswerText
    reading_refs: list[ReadingRef] = Field(min_length=1, max_length=8)
    limitations: list[LimitationText] = Field(max_length=3)
    safety: ReadingSafetyAssessment


class ReadingFollowUpSemanticError(ValueError):
    """Safe validation error containing only schema locations and categories."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(";".join(issues))


def allowed_reading_refs(result: ReadingFollowUpResult) -> set[str]:
    """Every section a follow-up may cite, derived from this exact reading."""
    values = {"title", "practical_step", "uncertainty_note", "safety"}
    values.update(f"possible_scenarios.{index}" for index in range(len(result.possible_scenarios)))
    values.update(
        f"reflection_questions.{index}" for index in range(len(result.reflection_questions))
    )
    if isinstance(result, ReadingResult):
        values.add("opening")
        values.update(f"symbols.{index}" for index in range(len(result.symbols)))
        values.update(f"patterns.{index}" for index in range(len(result.patterns)))
    else:
        values.add("overview")
        values.update(f"interpretations.{index}" for index in range(len(result.interpretations)))
        values.update(f"themes.{index}" for index in range(len(result.themes)))
    return values


def validate_reading_followup_semantics(
    answer: ReadingFollowUpAnswer,
    result: ReadingFollowUpResult,
) -> None:
    """Reject an answer that cites a section this reading does not contain."""
    issues: list[str] = []
    allowed = allowed_reading_refs(result)
    if len(answer.reading_refs) != len(set(answer.reading_refs)):
        issues.append("reading_refs:duplicate_reference")
    for reference in answer.reading_refs:
        if not re.fullmatch(_REFERENCE_PATTERN, reference) or reference not in allowed:
            issues.append("reading_refs:invalid_reference")
    if result.safety.high_risk_detected and not answer.safety.high_risk_detected:
        issues.append("safety:high_risk_downgrade")
    if issues:
        raise ReadingFollowUpSemanticError(issues)
