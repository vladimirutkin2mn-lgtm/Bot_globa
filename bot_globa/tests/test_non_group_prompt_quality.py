"""Focused regression tests for the non-group prompt and Daily quality upgrade."""

from datetime import date

import pytest

from app.domain.natal_chart import ZodiacSign
from app.domain.persona import persona_definition
from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.memory_extraction import (
    MEMORY_EXTRACTION_PROMPT_VERSION,
    load_memory_extraction_prompts,
)
from app.prompts.oracle import load_oracle_reading_prompts
from app.prompts.reading_followup import load_reading_followup_prompts
from app.research.personal_oracle_routing_eval import ROUTING_CASES, evaluate_routing
from app.services.daily_horoscope_ai_editor import (
    DailyHoroscopeAIEditor,
    DailyHoroscopeAIEditorError,
)
from app.services.daily_horoscope_longitudinal_eval import evaluate_longitudinal_daily
from app.services.daily_sky import DailyHoroscopeSnapshot, DailySignForecast


def test_legacy_and_new_individual_prompt_versions_are_both_loadable() -> None:
    for version in (
        "tarot-reader-v4",
        "tarot-reader-v5",
        "love-oracle-v2",
        "love-oracle-v3",
        "mystical-psychologist-v2",
        "mystical-psychologist-v3",
    ):
        assert load_oracle_reading_prompts(version).system
    for version in ("astrologer-v2", "astrologer-v3"):
        assert load_horoscope_prompts(version).system
    for version in ("reading_followup_v1", "reading_followup_v2"):
        assert load_reading_followup_prompts(version).system


def test_persona_defaults_use_new_prompt_versions() -> None:
    tarot = persona_definition("tarot_reader")
    love = persona_definition("love_oracle")
    psych = persona_definition("mystical_psychologist")
    astro = persona_definition("astrologer")
    assert tarot is not None and tarot.prompt_version == "tarot-reader-v5"
    assert love is not None and love.prompt_version == "love-oracle-v3"
    assert psych is not None and psych.prompt_version == "mystical-psychologist-v3"
    assert astro is not None and astro.prompt_version == "astrologer-v3"


def test_memory_extraction_prompt_is_versioned() -> None:
    prompt = load_memory_extraction_prompts(MEMORY_EXTRACTION_PROMPT_VERSION)
    assert "durable" in prompt.system
    with pytest.raises(LookupError):
        load_memory_extraction_prompts("oracle-memory-extractor-unknown")


def test_daily_repetition_guard_rejects_recent_duplicate() -> None:
    with pytest.raises(DailyHoroscopeAIEditorError):
        DailyHoroscopeAIEditor._reject_repetition(
            "Сегодня лучше не торопить разговор. Сначала уточните один важный вопрос.",
            ["Сегодня лучше не торопить разговор. Сначала уточните один важный вопрос."],
        )


def test_longitudinal_eval_exposes_same_sign_repetition() -> None:
    first = _snapshot(date(2026, 10, 1), suffix="первый")
    second = _snapshot(date(2026, 10, 2), suffix="первый")
    metrics = evaluate_longitudinal_daily((first, second))
    assert len(metrics) == len(ZodiacSign)
    assert all(item.exact_duplicate_ratio > 0 for item in metrics)
    assert all(not item.passes for item in metrics)


def test_routing_eval_is_fixed_and_reports_failures_instead_of_hiding_them() -> None:
    evaluation = evaluate_routing()
    assert evaluation.case_count == len(ROUTING_CASES)
    assert 0.0 <= evaluation.persona_accuracy <= 1.0
    assert 0.0 <= evaluation.exact_accuracy <= 1.0
    assert isinstance(evaluation.failed_case_ids, tuple)


def _snapshot(forecast_date: date, *, suffix: str) -> DailyHoroscopeSnapshot:
    signs = tuple(
        DailySignForecast(
            sign,
            f"{sign.value} прогноз {suffix}. Проверьте один конкретный шаг сегодня.",
        )
        for sign in ZodiacSign
    )
    return DailyHoroscopeSnapshot(
        forecast_date=forecast_date,
        sky_digest=f"digest-{forecast_date.isoformat()}",
        theme="Тестовая тема дня",
        signs=signs,
        sky_version="daily-sky-test",
        methodology_version="daily-method-test",
    )
