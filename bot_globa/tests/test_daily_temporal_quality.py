from datetime import date, timedelta

from app.domain.natal_chart import ZodiacSign
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_horoscope_temporal_quality import evaluate_same_sign_history


def test_temporal_quality_detects_repeated_same_sign_copy() -> None:
    first = build_editorial_daily_horoscope(date(2026, 10, 1))
    # Same snapshot twice models exactly the failure this metric is intended to catch.
    duplicate = build_editorial_daily_horoscope(date(2026, 10, 1))

    quality = evaluate_same_sign_history((first, duplicate), ZodiacSign.GEMINI)

    assert quality.exact_repeat_count == 1
    assert quality.has_repetition_problem is True


def test_temporal_quality_accepts_single_day() -> None:
    snapshot = build_editorial_daily_horoscope(date(2026, 10, 1) + timedelta(days=1))

    quality = evaluate_same_sign_history((snapshot,), ZodiacSign.ARIES)

    assert quality.days == 1
    assert quality.max_similarity == 0.0
