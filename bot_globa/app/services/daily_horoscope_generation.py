"""LLM editorial generation for the shared daily horoscope, grounded in app-owned sky facts."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.domain.natal_chart import ZodiacSign
from app.prompts.daily_horoscope import (
    DAILY_HOROSCOPE_PROMPT_VERSION,
    DAILY_HOROSCOPE_REQUEST_INSTRUCTION,
    DAILY_HOROSCOPE_SYSTEM_PROMPT,
)
from app.providers.llm.base import LLMClient, LLMRequest
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_sky import (
    DailyHoroscopeSnapshot,
    DailySignForecast,
    build_daily_horoscope,
    calculate_daily_sky,
)

DAILY_AI_METHOD_VERSION = "solar-sign-daily-ai-v1"
DAILY_AI_FALLBACK_METHOD_VERSION = "solar-sign-daily-ai-v1-fallback"
DAILY_AI_CURRENT_METHODS = frozenset(
    {DAILY_AI_METHOD_VERSION, DAILY_AI_FALLBACK_METHOD_VERSION}
)
DAILY_HISTORY_DAYS = 60
DAILY_PROMPT_HISTORY_DAYS = 8

DailyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=35, max_length=320),
]
ThemeText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=18, max_length=180),
]
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class DailyEditorialSign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sign: ZodiacSign
    text: DailyText


class DailyEditorialResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: ThemeText
    signs: list[DailyEditorialSign] = Field(min_length=12, max_length=12)


class InvalidDailyEditorialError(ValueError):
    """Safe validation error without generated horoscope text."""


@dataclass(frozen=True, slots=True)
class DailyRepetitionIssue:
    field: str
    days_ago: int
    similarity: float


class DailyHoroscopeGenerationService:
    """Generate one fresh shared digest per date and reject recent-copy repetition."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_repair_attempts: int = 1,
        similarity_threshold: float = 0.72,
    ) -> None:
        if max_repair_attempts not in {0, 1}:
            raise ValueError("daily horoscope supports at most one repair attempt")
        if not 0.5 <= similarity_threshold <= 1.0:
            raise ValueError("daily similarity threshold must be between 0.5 and 1.0")
        self._llm = llm
        self._max_repair_attempts = max_repair_attempts
        self._similarity_threshold = similarity_threshold

    @property
    def methodology_versions(self) -> frozenset[str]:
        return DAILY_AI_CURRENT_METHODS

    async def generate(
        self,
        forecast_date: date,
        history: Sequence[DailyHoroscopeSnapshot],
    ) -> DailyHoroscopeSnapshot:
        base = build_daily_horoscope(forecast_date)
        payload = self._input_payload(forecast_date, base, history)
        result = await self._complete(payload, repair=False)
        issues = self.repetition_issues(result, history)
        if issues and self._max_repair_attempts:
            repair_payload = dict(payload)
            repair_payload["repetition_repair"] = {
                "rejected_fields": [issue.field for issue in issues],
                "instruction": (
                    "Rewrite every rejected field with a materially different angle, opener and "
                    "practical action while staying grounded in the same supplied facts."
                ),
            }
            result = await self._complete(repair_payload, repair=True)
            issues = self.repetition_issues(result, history)
        if issues:
            raise InvalidDailyEditorialError("daily editorial repeats recent published copy")
        return self._snapshot(base, result, DAILY_AI_METHOD_VERSION)

    def fallback(self, forecast_date: date) -> DailyHoroscopeSnapshot:
        """Keep the broadcast available when the provider or editorial validation fails."""

        legacy = build_editorial_daily_horoscope(forecast_date)
        return DailyHoroscopeSnapshot(
            forecast_date=legacy.forecast_date,
            sky_digest=legacy.sky_digest,
            theme=legacy.theme,
            signs=legacy.signs,
            sky_version=legacy.sky_version,
            methodology_version=DAILY_AI_FALLBACK_METHOD_VERSION,
        )

    async def _complete(
        self,
        payload: dict[str, object],
        *,
        repair: bool,
    ) -> DailyEditorialResult:
        completion = await self._llm.generate_structured(
            LLMRequest(
                system_prompt=DAILY_HOROSCOPE_SYSTEM_PROMPT,
                user_prompt=(
                    DAILY_HOROSCOPE_REQUEST_INSTRUCTION
                    + "\n\nINPUT_JSON:\n"
                    + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                ),
                schema=DailyEditorialResult.model_json_schema(),
                message_ids=(str(payload["forecast_date"]),),
                participant_labels=(),
                repair=repair,
                telemetry_persona_code="daily_horoscope",
                telemetry_prompt_version=DAILY_HOROSCOPE_PROMPT_VERSION,
            )
        )
        try:
            result = DailyEditorialResult.model_validate_json(completion.payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidDailyEditorialError("invalid daily editorial payload") from exc
        expected = list(ZodiacSign)
        if [item.sign for item in result.signs] != expected:
            raise InvalidDailyEditorialError("daily editorial signs are not canonical")
        if len({self._normalize(item.text) for item in result.signs}) != len(result.signs):
            raise InvalidDailyEditorialError("daily editorial contains duplicate sign copy")
        return result

    def _input_payload(
        self,
        forecast_date: date,
        base: DailyHoroscopeSnapshot,
        history: Sequence[DailyHoroscopeSnapshot],
    ) -> dict[str, object]:
        sky = calculate_daily_sky(forecast_date)
        recent = sorted(
            (item for item in history if item.forecast_date < forecast_date),
            key=lambda item: item.forecast_date,
            reverse=True,
        )[:DAILY_PROMPT_HISTORY_DAYS]
        return {
            "forecast_date": forecast_date.isoformat(),
            "canonical_signs": [sign.value for sign in ZodiacSign],
            "sky": sky.payload(),
            "shared_theme_signal": base.theme,
            "sign_signals": [item.payload() for item in base.signs],
            "recent_history": [
                {
                    "forecast_date": item.forecast_date.isoformat(),
                    "theme": item.theme,
                    "signs": [sign.payload() for sign in item.signs],
                }
                for item in recent
            ],
        }

    def repetition_issues(
        self,
        result: DailyEditorialResult,
        history: Sequence[DailyHoroscopeSnapshot],
    ) -> tuple[DailyRepetitionIssue, ...]:
        """Catch same-sign temporal repetition that cross-sign benchmarks cannot see."""

        issues: list[DailyRepetitionIssue] = []
        recent = sorted(history, key=lambda item: item.forecast_date, reverse=True)[:DAILY_HISTORY_DAYS]
        theme_tokens = self._tokens(result.theme)
        for days_ago, snapshot in enumerate(recent, start=1):
            similarity = self._similarity(theme_tokens, self._tokens(snapshot.theme))
            if similarity >= self._similarity_threshold:
                issues.append(DailyRepetitionIssue("theme", days_ago, similarity))
                break

        generated = {item.sign: item.text for item in result.signs}
        for sign in ZodiacSign:
            current = generated[sign]
            current_tokens = self._tokens(current)
            for days_ago, snapshot in enumerate(recent, start=1):
                previous = next(item.text for item in snapshot.signs if item.sign is sign)
                similarity = self._similarity(current_tokens, self._tokens(previous))
                if self._normalize(current) == self._normalize(previous) or similarity >= self._similarity_threshold:
                    issues.append(
                        DailyRepetitionIssue(f"sign:{sign.value}", days_ago, similarity)
                    )
                    break
        return tuple(issues)

    @staticmethod
    def _snapshot(
        base: DailyHoroscopeSnapshot,
        result: DailyEditorialResult,
        methodology_version: str,
    ) -> DailyHoroscopeSnapshot:
        return DailyHoroscopeSnapshot(
            forecast_date=base.forecast_date,
            sky_digest=base.sky_digest,
            theme=result.theme.rstrip(". "),
            signs=tuple(DailySignForecast(item.sign, item.text) for item in result.signs),
            sky_version=base.sky_version,
            methodology_version=methodology_version,
        )

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        return {
            token
            for token in (match.group(0).casefold() for match in _TOKEN_RE.finditer(value))
            if len(token) >= 3
        }

    @staticmethod
    def _similarity(first: set[str], second: set[str]) -> float:
        if not first or not second:
            return 0.0
        return len(first & second) / len(first | second)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().split()).strip(" .,!?:;—–-")
