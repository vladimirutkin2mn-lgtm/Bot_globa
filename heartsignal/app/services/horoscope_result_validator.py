"""Parse and validate fact-bound Horoscope output without exposing payload text."""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.domain.horoscope import (
    ASTROLOGY_READING_SCHEMA_VERSION,
    AstrologyReadingResult,
    AstrologyReadingSemanticError,
    HoroscopeFactBundle,
    validate_astrology_reading_semantics,
    visible_astrology_texts,
)
from app.services.reading_output_safety import (
    ReadingOutputSafetyError,
    ReadingOutputSafetyValidator,
)


class InvalidHoroscopeResult(ValueError):
    """Safe invalid-output error containing codes and field paths only."""

    def __init__(self, code: str, issues: tuple[str, ...] = ()) -> None:
        self.code = code
        self.issues = issues
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class HoroscopeResultValidation:
    result: AstrologyReadingResult
    schema_version: str


class HoroscopeResultValidator:
    """Validate JSON shape, fact references, limitations and shared output safety."""

    schema_version = ASTROLOGY_READING_SCHEMA_VERSION

    def __init__(
        self,
        output_safety: ReadingOutputSafetyValidator | None = None,
    ) -> None:
        self._output_safety = output_safety or ReadingOutputSafetyValidator()

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return AstrologyReadingResult.model_json_schema()

    def validate(
        self,
        payload: str,
        expected_facts: HoroscopeFactBundle,
    ) -> HoroscopeResultValidation:
        result = self._parse(payload)
        try:
            validate_astrology_reading_semantics(result, expected_facts)
        except AstrologyReadingSemanticError as exc:
            raise InvalidHoroscopeResult("invalid_semantics", tuple(exc.issues)) from exc
        self._validate_safety(result)
        return HoroscopeResultValidation(result=result, schema_version=self.schema_version)

    def validate_stored(self, payload: dict[str, object]) -> HoroscopeResultValidation:
        """Validate persisted ciphertext after fact-bound validation already succeeded."""

        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise InvalidHoroscopeResult("invalid_json") from exc
        result = self._parse(serialized)
        self._validate_safety(result)
        return HoroscopeResultValidation(result=result, schema_version=self.schema_version)

    def _parse(self, payload: str) -> AstrologyReadingResult:
        try:
            json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidHoroscopeResult("invalid_json") from exc
        try:
            return AstrologyReadingResult.model_validate_json(payload)
        except ValidationError as exc:
            issues = tuple(
                ".".join(str(part) for part in error["loc"]) + ":invalid"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise InvalidHoroscopeResult("invalid_schema", issues) from exc

    def _validate_safety(self, result: AstrologyReadingResult) -> None:
        try:
            self._output_safety.validate_texts(visible_astrology_texts(result))
        except ReadingOutputSafetyError as exc:
            raise InvalidHoroscopeResult("unsafe_output", exc.issues) from exc

    @staticmethod
    def repair_instruction(error: InvalidHoroscopeResult) -> str:
        """Create one payload-free correction instruction for a controlled retry."""

        issue_lines = "\n".join(f"- {issue}" for issue in error.issues[:20])
        suffix = f"\nDetected issues:\n{issue_lines}" if issue_lines else ""
        safety_instruction = ""
        if error.code == "unsafe_output":
            safety_instruction = (
                " Remove guaranteed outcomes, exact future dates, third-party mind reading, "
                "diagnoses, professional directions, violence, stalking, fear-based upsells "
                "and dependency-inducing language. Use conditional reflection instead."
            )
        return (
            "Return one complete JSON object matching the supplied schema. Copy scope and "
            "facts_digest exactly, use only supplied fact_id values, and include every supplied "
            "limitation. Do not write planet names, zodiac signs, houses, ascendant labels or "
            "degree values in narrative text. Do not add Markdown, commentary or extra fields."
            f"{safety_instruction}{suffix}"
        )
