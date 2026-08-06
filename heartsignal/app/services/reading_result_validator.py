"""Parse and validate structured ReadingResult payloads safely."""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.domain.reading import ReadingSymbolInput
from app.domain.reading_result import (
    ReadingResult,
    ReadingSemanticValidationError,
    validate_reading_semantics,
)
from app.services.reading_output_safety import (
    ReadingOutputSafetyError,
    ReadingOutputSafetyValidator,
)


class InvalidReadingResult(ValueError):
    """Safe invalid-output error that never contains the model payload."""

    def __init__(self, code: str, issues: tuple[str, ...] = ()) -> None:
        self.code = code
        self.issues = issues
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ReadingResultValidation:
    result: ReadingResult
    schema_version: str


class ReadingResultValidator:
    """Validate JSON shape, symbol semantics, and output safety."""

    schema_version = "reading-result-v1"

    def __init__(
        self,
        output_safety: ReadingOutputSafetyValidator | None = None,
    ) -> None:
        self._output_safety = output_safety or ReadingOutputSafetyValidator()

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return ReadingResult.model_json_schema()

    def validate(
        self,
        payload: str,
        expected_symbols: list[ReadingSymbolInput],
    ) -> ReadingResultValidation:
        try:
            json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidReadingResult("invalid_json") from exc
        try:
            result = ReadingResult.model_validate_json(payload)
        except ValidationError as exc:
            issues = tuple(
                ".".join(str(part) for part in error["loc"]) + ":invalid"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise InvalidReadingResult("invalid_schema", issues) from exc
        try:
            validate_reading_semantics(result, expected_symbols)
        except ReadingSemanticValidationError as exc:
            raise InvalidReadingResult("invalid_semantics", tuple(exc.issues)) from exc
        try:
            self._output_safety.validate(result)
        except ReadingOutputSafetyError as exc:
            raise InvalidReadingResult("unsafe_output", exc.issues) from exc
        return ReadingResultValidation(result=result, schema_version=self.schema_version)

    @staticmethod
    def repair_instruction(error: InvalidReadingResult) -> str:
        """Build a payload-free correction instruction for one controlled retry."""

        issue_lines = "\n".join(f"- {issue}" for issue in error.issues[:20])
        suffix = f"\nDetected issues:\n{issue_lines}" if issue_lines else ""
        safety_instruction = ""
        if error.code == "unsafe_output":
            safety_instruction = (
                " Remove claims of guaranteed outcomes or exact dates, third-party mind "
                "reading, diagnoses, legal or financial directions, violence or stalking "
                "instructions, fear-based upsells, and dependency-inducing language. "
                "Use conditional and reflective wording instead."
            )
        return (
            "Return a complete JSON object matching the supplied schema. "
            "Use exactly the application-provided symbol IDs, positions and orientations. "
            "Do not add Markdown, commentary or extra fields."
            f"{safety_instruction}{suffix}"
        )
