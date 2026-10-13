"""Grounded LLM editor for one shared twelve-sign daily horoscope snapshot."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.domain.natal_chart import ZodiacSign
from app.prompts.daily_horoscope import (
    DAILY_HOROSCOPE_PROMPT_VERSION,
    load_daily_horoscope_prompts,
)
from app.providers.llm.base import LLMClient, LLMRequest
from app.services.daily_sky import DailyHoroscopeSnapshot, DailySignForecast


DAILY_AI_METHOD_VERSION = "solar-sign-daily-ai-v1"
DAILY_AI_FALLBACK_METHOD_VERSION = "solar-sign-daily-ai-v1-fallback"
DAILY_HISTORY_DAYS = 60
DAILY_PROMPT_HISTORY_DAYS = 30

_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["theme", "signs"],
    "properties": {
        "theme": {"type": "string", "minLength": 8, "maxLength": 120},
        "signs": {
            "type": "array",
            "minItems": 12,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sign", "headline", "central_idea", "action", "text"],
                "properties": {
                    "sign": {"type": "string"},
                    "headline": {"type": "string", "minLength": 3, "maxLength": 70},
                    "central_idea": {"type": "string", "minLength": 3, "maxLength": 100},
                    "action": {"type": "string", "minLength": 3, "maxLength": 120},
                    "text": {"type": "string", "minLength": 35, "maxLength": 240},
                },
            },
        },
    },
}

_FORBIDDEN_ASTRO_DETAIL = re.compile(
    r"\b(?:меркур(?:ий|ия)|венер(?:а|ы)|марс(?:а)?|юпитер(?:а)?|сатурн(?:а)?|"
    r"уран(?:а)?|нептун(?:а)?|плутон(?:а)?|аспект(?:а|ы|ов)?|трин(?:а|ы)?|"
    r"секстил(?:ь|я|и)?|квадратур(?:а|ы)|оппозици(?:я|и)|\d{1,2}-?й дом)\b",
    re.IGNORECASE,
)
_FORBIDDEN_CERTAINTY = re.compile(
    r"\b(?:гарантированно|неизбежно|точно произойд|обязательно случ|предопределен)\w*",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


class InvalidDailyHoroscopeAIResultError(ValueError):
    """The model returned structurally valid JSON that is unsafe, stale or repetitive."""


@dataclass(frozen=True, slots=True)
class DailyHoroscopeAIResult:
    snapshot: DailyHoroscopeSnapshot
    editorial_meta: dict[str, dict[str, str]]


class DailyHoroscopeAIEditor:
    """Turn deterministic sign signals into human copy without changing their facts."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def generate(
        self,
        base: DailyHoroscopeSnapshot,
        recent_history: dict[str, list[dict[str, str]]],
    ) -> DailyHoroscopeAIResult:
        prompts = load_daily_horoscope_prompts(DAILY_HOROSCOPE_PROMPT_VERSION)
        facts = _daily_facts(base)
        prompt_history = {
            sign: entries[:DAILY_PROMPT_HISTORY_DAYS] for sign, entries in recent_history.items()
        }
        completion = await self._llm.generate_structured(
            LLMRequest(
                system_prompt=prompts.system,
                user_prompt=prompts.request.format(
                    forecast_date=base.forecast_date.isoformat(),
                    daily_facts_json=json.dumps(facts, ensure_ascii=False, separators=(",", ":")),
                    recent_history_json=json.dumps(
                        prompt_history, ensure_ascii=False, separators=(",", ":")
                    ),
                ),
                schema=_SCHEMA,
                message_ids=(),
                participant_labels=(),
                telemetry_persona_code="daily_horoscope",
                telemetry_prompt_version=prompts.version,
            )
        )
        try:
            payload = json.loads(completion.payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise InvalidDailyHoroscopeAIResultError("daily AI returned invalid JSON") from exc
        return _validate_and_build(base, payload, recent_history)


def _daily_facts(base: DailyHoroscopeSnapshot) -> dict[str, object]:
    signs: list[dict[str, str]] = []
    for item in base.signs:
        topic, separator, signal = item.text.partition(": ")
        signs.append(
            {
                "sign": item.sign.value,
                "topic": topic if separator else "общий фокус",
                "signal": signal if separator else item.text,
            }
        )
    return {
        "forecast_date": base.forecast_date.isoformat(),
        "sky_digest": base.sky_digest,
        "theme_seed": base.theme,
        "canonical_order": [sign.value for sign in ZodiacSign],
        "signs": signs,
    }


def _validate_and_build(
    base: DailyHoroscopeSnapshot,
    payload: Any,
    recent_history: dict[str, list[dict[str, str]]],
) -> DailyHoroscopeAIResult:
    if not isinstance(payload, dict):
        raise InvalidDailyHoroscopeAIResultError("daily AI payload must be an object")
    theme = _bounded_text(payload.get("theme"), "theme", 8, 120)
    raw_signs = payload.get("signs")
    if not isinstance(raw_signs, list) or len(raw_signs) != len(ZodiacSign):
        raise InvalidDailyHoroscopeAIResultError("daily AI must return exactly twelve signs")

    expected = tuple(sign.value for sign in ZodiacSign)
    received: list[str] = []
    forecasts: list[DailySignForecast] = []
    metadata: dict[str, dict[str, str]] = {}
    day_texts: list[str] = []
    day_actions: list[str] = []

    for index, raw in enumerate(raw_signs):
        if not isinstance(raw, dict):
            raise InvalidDailyHoroscopeAIResultError("daily AI sign item must be an object")
        sign = _bounded_text(raw.get("sign"), "sign", 3, 16)
        received.append(sign)
        if sign != expected[index]:
            raise InvalidDailyHoroscopeAIResultError("daily AI changed canonical zodiac order")
        headline = _bounded_text(raw.get("headline"), "headline", 3, 70)
        central = _bounded_text(raw.get("central_idea"), "central_idea", 3, 100)
        action = _bounded_text(raw.get("action"), "action", 3, 120)
        text = _bounded_text(raw.get("text"), "text", 35, 240)
        visible = f"{_sentence(headline)} {text}".strip()
        _validate_language(visible)
        _validate_history(sign, visible, headline, central, action, recent_history.get(sign, []))
        if any(_similar(visible, other) >= 0.90 for other in day_texts):
            raise InvalidDailyHoroscopeAIResultError("daily AI repeated a forecast across signs")
        if any(_idea_similarity(action, other) >= 0.86 for other in day_actions):
            raise InvalidDailyHoroscopeAIResultError("daily AI repeated the same action across signs")
        day_texts.append(visible)
        day_actions.append(action)
        forecasts.append(DailySignForecast(ZodiacSign(sign), visible))
        metadata[sign] = {
            "headline": headline,
            "central_idea": central,
            "action": action,
            "text": visible,
        }

    if tuple(received) != expected:
        raise InvalidDailyHoroscopeAIResultError("daily AI sign set mismatch")
    if _FORBIDDEN_ASTRO_DETAIL.search(theme) or _FORBIDDEN_CERTAINTY.search(theme):
        raise InvalidDailyHoroscopeAIResultError("daily AI theme contains unsupported claims")

    snapshot = DailyHoroscopeSnapshot(
        forecast_date=base.forecast_date,
        sky_digest=base.sky_digest,
        theme=theme.rstrip(". "),
        signs=tuple(forecasts),
        sky_version=base.sky_version,
        methodology_version=DAILY_AI_METHOD_VERSION,
    )
    return DailyHoroscopeAIResult(snapshot=snapshot, editorial_meta=metadata)


def _validate_language(text: str) -> None:
    if _FORBIDDEN_ASTRO_DETAIL.search(text):
        raise InvalidDailyHoroscopeAIResultError("daily AI invented astrological details")
    if _FORBIDDEN_CERTAINTY.search(text):
        raise InvalidDailyHoroscopeAIResultError("daily AI used deterministic future language")


def _validate_history(
    sign: str,
    text: str,
    headline: str,
    central: str,
    action: str,
    entries: list[dict[str, str]],
) -> None:
    for entry in entries[:DAILY_HISTORY_DAYS]:
        previous_text = entry.get("text", "")
        if previous_text and _similar(text, previous_text) >= 0.88:
            raise InvalidDailyHoroscopeAIResultError(f"daily AI repeated recent text for {sign}")
        previous_headline = entry.get("headline", "")
        if previous_headline and _similar(headline, previous_headline) >= 0.86:
            raise InvalidDailyHoroscopeAIResultError(f"daily AI repeated recent headline for {sign}")
        previous_central = entry.get("central_idea", "")
        if previous_central and _idea_similarity(central, previous_central) >= 0.78:
            raise InvalidDailyHoroscopeAIResultError(f"daily AI repeated recent idea for {sign}")
        previous_action = entry.get("action", "")
        if previous_action and _idea_similarity(action, previous_action) >= 0.78:
            raise InvalidDailyHoroscopeAIResultError(f"daily AI repeated recent action for {sign}")


def _bounded_text(value: object, name: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidDailyHoroscopeAIResultError(f"daily AI {name} must be text")
    clean = " ".join(value.split()).strip()
    if not minimum <= len(clean) <= maximum:
        raise InvalidDailyHoroscopeAIResultError(f"daily AI {name} has invalid length")
    return clean


def _sentence(value: str) -> str:
    return value if value.endswith((".", "!", "?", "…")) else f"{value}."


def _normal(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.casefold().replace("ё", "е")))


def _similar(first: str, second: str) -> float:
    left = _normal(first)
    right = _normal(second)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _idea_similarity(first: str, second: str) -> float:
    left = set(_WORD_RE.findall(first.casefold().replace("ё", "е")))
    right = set(_WORD_RE.findall(second.casefold().replace("ё", "е")))
    if not left or not right:
        return 0.0
    jaccard = len(left & right) / len(left | right)
    sequence = _similar(first, second)
    return max(jaccard, sequence)
