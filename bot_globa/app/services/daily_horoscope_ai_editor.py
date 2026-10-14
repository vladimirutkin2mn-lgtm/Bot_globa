"""One-call AI editorial layer for the shared daily horoscope.

Astrology remains deterministic in ``daily_sky``. This module only turns the already-selected
per-sign signals into natural Russian prose, validates the batch, and rejects longitudinal
repetition before a shared snapshot is persisted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from app.domain.natal_chart import ZodiacSign
from app.prompts.daily_horoscope_editor import (
    DAILY_HOROSCOPE_EDITOR_PROMPT_VERSION,
    load_daily_horoscope_editor_prompts,
)
from app.providers.llm.base import LLMClient, LLMRequest
from app.services.daily_sky import (
    DailyHoroscopeSnapshot,
    DailySignForecast,
    build_daily_horoscope,
)

DAILY_AI_METHOD_VERSION = "solar-sign-daily-ai-v1"
DAILY_AI_FALLBACK_VERSION = "solar-sign-daily-ai-v1-fallback"
_HISTORY_DAYS = 60
_HISTORY_IN_PROMPT = 5
_MIN_TEXT = 70
_MAX_TEXT = 600
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_CERTAINTY_RE = re.compile(
    r"\b(точно|обязательно|гарантирован\w*|неизбежн\w*|произойд[её]т|случится)\b",
    re.IGNORECASE,
)
_ASTROLOGY_TERMS = (
    "солнц",
    "лун",
    "меркур",
    "венер",
    "марс",
    "юпитер",
    "сатурн",
    "уран",
    "нептун",
    "плутон",
    "соединен",
    "соединён",
    "секстил",
    "квадрат",
    "трин",
    "оппозиц",
    "асцендент",
)


class DailyHoroscopeAIEditorError(ValueError):
    pass


class _SignDraft(BaseModel):
    sign: str
    text: str = Field(min_length=_MIN_TEXT, max_length=_MAX_TEXT)


class _BatchDraft(BaseModel):
    theme: str = Field(min_length=20, max_length=240)
    signs: list[_SignDraft] = Field(min_length=12, max_length=12)


class DailyHoroscopeAIEditor:
    """Generate all twelve common forecasts in one structured LLM call."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def generate(
        self,
        forecast_date: date,
        history: Iterable[DailyHoroscopeSnapshot] = (),
    ) -> DailyHoroscopeSnapshot:
        base = build_daily_horoscope(forecast_date)
        recent = tuple(history)
        prompts = load_daily_horoscope_editor_prompts(DAILY_HOROSCOPE_EDITOR_PROMPT_VERSION)
        facts = {
            "forecast_date": forecast_date.isoformat(),
            "sky_digest": base.sky_digest,
            "base_theme": base.theme,
            "signs": [item.payload() for item in base.signs],
        }
        history_payload = self._history_for_prompt(recent)
        request = LLMRequest(
            system_prompt=prompts.system,
            user_prompt=(
                f"{prompts.request_instruction}\n\nDAILY_FACTS_JSON:\n"
                f"{json.dumps(facts, ensure_ascii=False, separators=(',', ':'))}\n\n"
                f"HISTORY_JSON:\n"
                f"{json.dumps(history_payload, ensure_ascii=False, separators=(',', ':'))}"
            ),
            schema=_BatchDraft.model_json_schema(),
            message_ids=(forecast_date.isoformat(),),
            participant_labels=(),
            telemetry_persona_code="daily_horoscope",
            telemetry_prompt_version=DAILY_HOROSCOPE_EDITOR_PROMPT_VERSION,
        )
        completion = await self._llm.generate_structured(request)
        try:
            draft = _BatchDraft.model_validate_json(completion.payload)
        except ValidationError as error:
            raise DailyHoroscopeAIEditorError("daily AI editor returned invalid schema") from error
        return self._validate_and_build(base, draft, recent)

    @staticmethod
    def _history_for_prompt(
        history: tuple[DailyHoroscopeSnapshot, ...],
    ) -> dict[str, list[str]]:
        by_sign: dict[str, list[str]] = {sign.value: [] for sign in ZodiacSign}
        for snapshot in sorted(history, key=lambda item: item.forecast_date, reverse=True):
            for item in snapshot.signs:
                bucket = by_sign[item.sign.value]
                if len(bucket) < _HISTORY_IN_PROMPT:
                    bucket.append(item.text)
        return by_sign

    def _validate_and_build(
        self,
        base: DailyHoroscopeSnapshot,
        draft: _BatchDraft,
        history: tuple[DailyHoroscopeSnapshot, ...],
    ) -> DailyHoroscopeSnapshot:
        expected = [sign.value for sign in ZodiacSign]
        actual = [item.sign for item in draft.signs]
        if actual != expected:
            raise DailyHoroscopeAIEditorError("daily AI editor changed canonical zodiac order")
        texts = [self._clean(item.text) for item in draft.signs]
        if len(set(texts)) != len(texts):
            raise DailyHoroscopeAIEditorError("daily AI editor duplicated texts inside one day")

        all_source = " ".join((base.theme, *(item.text for item in base.signs)))
        clean_theme = self._clean(draft.theme)
        self._reject_unsupported_claims(clean_theme, all_source)

        recent_by_sign: dict[ZodiacSign, list[str]] = {sign: [] for sign in ZodiacSign}
        cutoff = base.forecast_date.toordinal() - _HISTORY_DAYS
        for snapshot in history:
            if snapshot.forecast_date.toordinal() < cutoff:
                continue
            for item in snapshot.signs:
                recent_by_sign[item.sign].append(item.text)

        forecasts: list[DailySignForecast] = []
        for source, item, text in zip(base.signs, draft.signs, texts, strict=True):
            if source.sign.value != item.sign:
                raise DailyHoroscopeAIEditorError("daily AI editor changed sign identity")
            self._reject_unsupported_claims(text, f"{base.theme} {source.text}")
            self._reject_repetition(text, recent_by_sign[source.sign])
            forecasts.append(DailySignForecast(source.sign, text))

        return DailyHoroscopeSnapshot(
            forecast_date=base.forecast_date,
            sky_digest=base.sky_digest,
            theme=clean_theme,
            signs=tuple(forecasts),
            sky_version=base.sky_version,
            methodology_version=DAILY_AI_METHOD_VERSION,
        )

    @staticmethod
    def _reject_unsupported_claims(candidate: str, source: str) -> None:
        if _CERTAINTY_RE.search(candidate):
            raise DailyHoroscopeAIEditorError("daily AI editor introduced deterministic certainty")
        candidate_lower = candidate.casefold()
        source_lower = source.casefold()
        for term in _ASTROLOGY_TERMS:
            if term in candidate_lower and term not in source_lower:
                raise DailyHoroscopeAIEditorError(
                    "daily AI editor introduced unsupported astrology detail"
                )

    @classmethod
    def _reject_repetition(cls, candidate: str, previous: Iterable[str]) -> None:
        normalized = cls._normalize(candidate)
        opening = cls._opening(candidate)
        action = cls._action(candidate)
        for old in previous:
            old_normalized = cls._normalize(old)
            if normalized == old_normalized:
                raise DailyHoroscopeAIEditorError(
                    "daily AI editor repeated an exact recent forecast"
                )
            if cls._similarity(normalized, old_normalized) >= 0.72:
                raise DailyHoroscopeAIEditorError("daily AI editor repeated a recent central idea")
            if cls._similarity(cls._normalize(opening), cls._normalize(cls._opening(old))) >= 0.74:
                raise DailyHoroscopeAIEditorError("daily AI editor repeated a recent opening")
            if cls._similarity(cls._normalize(action), cls._normalize(cls._action(old))) >= 0.78:
                raise DailyHoroscopeAIEditorError("daily AI editor repeated a recent action")

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.split()).strip()

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(_TOKEN_RE.findall(text.lower()))

    @staticmethod
    def _opening(text: str) -> str:
        return re.split(r"[.!?]", text, maxsplit=1)[0]

    @staticmethod
    def _action(text: str) -> str:
        parts = [part.strip() for part in re.split(r"[.!?]", text) if part.strip()]
        return parts[-1] if parts else text

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        a = {token for token in left.split() if len(token) >= 4}
        b = {token for token in right.split() if len(token) >= 4}
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)
