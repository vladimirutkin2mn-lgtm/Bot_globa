"""Bound untrusted oracle data and validate share-safe structured text."""

import json
import re
from collections.abc import Mapping, Sequence

from app.domain.reading_result import ShareCardPayload
from app.services.reading_output_safety import (
    ReadingOutputSafetyError,
    ReadingOutputSafetyValidator,
)


class OracleBoundaryError(ValueError):
    """Payload-free boundary error with stable machine-readable issue codes."""

    def __init__(self, code: str, issues: tuple[str, ...] = ()) -> None:
        self.code = code
        self.issues = issues
        super().__init__(code)


class OraclePromptBoundary:
    """Serialize user and memory content as data, never as prompt instructions."""

    input_marker = "INPUT_JSON:\n"
    memory_marker = "MEMORY_JSON:\n"

    @classmethod
    def wrap_input(cls, payload: Mapping[str, object]) -> str:
        return cls.input_marker + cls._dump(dict(payload))

    @classmethod
    def wrap_memory(cls, items: Sequence[Mapping[str, object]]) -> str:
        return cls.memory_marker + cls._dump({"items": [dict(item) for item in items]})

    @staticmethod
    def _dump(payload: object) -> str:
        try:
            return json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise OracleBoundaryError("unserializable_untrusted_context") from exc


_PROMPT_CONTROL_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bignore (?:all |the )?(?:previous|prior) instructions\b",
        r"\breveal (?:the )?(?:system|developer) prompt\b",
        r"\b(?:system|developer) message\s*:",
        r"<\|(?:system|developer|assistant|user)\|>",
        r"\bbegin (?:system|developer) instructions\b",
        r"\bигнорируй (?:все )?(?:предыдущие|прошлые) инструкции\b",
        r"\bпокажи (?:системный|developer) промпт\b",
        r"\bсистемное сообщение\s*:",
    )
)


class OracleShareSanitizer:
    """Reject unsafe or private share-card text before it can leave the product."""

    min_private_fragment_length = 4

    def __init__(
        self,
        output_safety: ReadingOutputSafetyValidator | None = None,
    ) -> None:
        self._output_safety = output_safety or ReadingOutputSafetyValidator()

    def validate(
        self,
        payload: ShareCardPayload,
        *,
        private_fragments: Sequence[str] = (),
    ) -> None:
        visible = (
            ("share_card.headline", payload.headline),
            ("share_card.short_text", payload.short_text),
        )
        issues: list[str] = []
        try:
            self._output_safety.validate_texts(visible)
        except ReadingOutputSafetyError as exc:
            issues.extend(exc.issues)

        normalized_visible = " ".join(self._normalize(value) for _, value in visible)
        for fragment in private_fragments:
            normalized_fragment = self._normalize(fragment)
            if (
                len(normalized_fragment) >= self.min_private_fragment_length
                and normalized_fragment in normalized_visible
            ):
                issues.append("output.share_card:private_content")

        for path, value in visible:
            normalized = self._normalize(value)
            if any(pattern.search(normalized) for pattern in _PROMPT_CONTROL_PATTERNS):
                issues.append(f"output.{path}:prompt_control")

        unique = tuple(dict.fromkeys(issues))
        if unique:
            raise OracleBoundaryError("unsafe_share", unique)

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()
