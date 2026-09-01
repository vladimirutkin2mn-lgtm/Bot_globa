from datetime import date

from app.domain.natal_chart import ZodiacSign
from app.research.daily_horoscope_candidate import build_candidate_daily_horoscope
from app.research.daily_horoscope_evaluator import evaluate_builder
from app.services.daily_horoscope_benchmark import BenchmarkForecast, build_benchmark_metrics
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_sky import DailyHoroscopeSnapshot, DailySignForecast


def test_v7_action_language_is_recognized_by_benchmark() -> None:
    forecasts = [
        BenchmarkForecast(ZodiacSign.ARIES, "Разговор изменит планы — задайте прямой вопрос."),
        BenchmarkForecast(ZodiacSign.TAURUS, "В переписке всплывёт нюанс — перечитайте детали."),
        BenchmarkForecast(ZodiacSign.GEMINI, "Карьерный вопрос сдвинется — инициируйте разговор."),
    ]

    metrics = build_benchmark_metrics(forecasts)

    assert metrics.actionable_ratio == 1.0


def test_autoresearch_candidate_starts_from_production_v7_copy() -> None:
    forecast_date = date(2026, 9, 1)
    candidate = build_candidate_daily_horoscope(forecast_date)
    production = build_editorial_daily_horoscope(forecast_date)

    assert [item.text for item in candidate.signs] == [item.text for item in production.signs]
    assert candidate.theme == production.theme
    assert candidate.sky_digest == production.sky_digest


def test_autoresearch_v7_baseline_passes_sample_product_gates() -> None:
    evaluation = evaluate_builder(build_editorial_daily_horoscope, days=14)

    assert evaluation.gates_passed
    assert evaluation.numa_score > 0
    assert all(evaluation.hard_gates.values())


def test_autoresearch_invalid_repetition_zeroes_numa_score() -> None:
    def repetitive_builder(forecast_date: date) -> DailyHoroscopeSnapshot:
        source = build_editorial_daily_horoscope(forecast_date)
        repeated = source.signs[0].text
        signs = tuple(DailySignForecast(sign, repeated) for sign in ZodiacSign)
        return DailyHoroscopeSnapshot(
            forecast_date=source.forecast_date,
            sky_digest=source.sky_digest,
            theme=source.theme,
            signs=signs,
            sky_version=source.sky_version,
            methodology_version="autoresearch-invalid-test",
        )

    evaluation = evaluate_builder(repetitive_builder, days=14)

    assert not evaluation.gates_passed
    assert not evaluation.hard_gates["daily_sign_copy_unique"]
    assert evaluation.numa_score == 0.0
