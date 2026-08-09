"""Deterministic local structured-output provider for Oracle development and CI."""

import json
from typing import Literal, cast

from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMCompletion,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
)

StubBehavior = Literal[
    "success",
    "invalid_json",
    "invalid_schema",
    "invalid_semantics",
    "timeout",
    "rate_limit",
    "authentication_error",
    "transport_error",
    "repair_success",
    "repair_failure",
]


class StubLLMClient:
    """Return deterministic Oracle-compatible JSON without external network calls."""

    def __init__(self, model: str = "stub", behavior: StubBehavior = "success") -> None:
        self.model, self.behavior, self.calls = model, behavior, 0

    async def aclose(self) -> None:
        return None

    async def generate_analysis(self, request: LLMRequest) -> LLMCompletion:
        self.calls += 1
        if self.behavior == "timeout":
            raise LLMTimeoutError
        if self.behavior == "rate_limit":
            raise LLMRateLimitError
        if self.behavior == "authentication_error":
            raise LLMAuthenticationError
        if self.behavior == "transport_error":
            raise LLMTransientError

        invalid_schema = self.behavior == "invalid_schema"
        invalid_semantics = self.behavior == "invalid_semantics"
        if self.behavior == "repair_success" and not request.repair:
            invalid_schema = True
        if self.behavior == "repair_failure":
            invalid_schema = True

        if self.behavior == "invalid_json":
            payload = "{not-json"
        elif invalid_schema:
            payload = json.dumps({"title": "incomplete"}, ensure_ascii=False)
        else:
            payload = json.dumps(
                self._reading_result(request, invalid_semantics=invalid_semantics),
                ensure_ascii=False,
            )
        return LLMCompletion(payload, "stub", self.model, "stub-request", 120, 240, 1)

    @staticmethod
    def _input_payload(request: LLMRequest) -> dict[str, object]:
        marker = "INPUT_JSON:\n"
        if marker not in request.user_prompt:
            return {}
        raw = request.user_prompt.split(marker, 1)[1]
        raw = raw.split("\n\nCORRECTION_INSTRUCTION:", 1)[0]
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}

    @classmethod
    def _reading_result(
        cls,
        request: LLMRequest,
        *,
        invalid_semantics: bool,
    ) -> dict[str, object]:
        source = cls._input_payload(request)
        selected = source.get("selected_symbols")
        symbol_rows = selected if isinstance(selected, list) else []
        symbols: list[dict[str, object]] = []
        for index, item in enumerate(symbol_rows):
            if not isinstance(item, dict):
                continue
            symbol_id = str(item.get("symbol_id", f"symbol_{index + 1}"))
            if invalid_semantics and index == 0:
                symbol_id = "unexpected_symbol"
            symbols.append(
                {
                    "symbol_id": symbol_id,
                    "position": str(item.get("position", f"position_{index + 1}")),
                    "orientation": str(item.get("orientation", "upright")),
                    "interpretation": (
                        "Символ предлагает рассмотреть ситуацию как повод для наблюдения, "
                        "а не как гарантированное предсказание."
                    ),
                }
            )
        return {
            "title": "Рефлексивный разбор",
            "opening": (
                "Этот результат — символическая интерпретация для размышления, "
                "а не достоверное знание о будущем или других людях."
            ),
            "symbols": symbols,
            "patterns": ["Полезно отделить наблюдаемые факты от возможных интерпретаций."],
            "possible_scenarios": [
                {
                    "scenario": "Ситуация может проясниться после дополнительной информации.",
                    "conditions": ["Появятся новые наблюдаемые факты."],
                }
            ],
            "reflection_questions": ["Какой следующий шаг остаётся обратимым и проверяемым?"],
            "practical_step": "Выберите один небольшой обратимый шаг и оцените его результат.",
            "uncertainty_note": "Неопределённость остаётся; символы не подтверждают факты.",
            "share_card": {
                "headline": "Символический взгляд",
                "short_text": "Наблюдай факты, сохраняй пространство для неопределённости.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
