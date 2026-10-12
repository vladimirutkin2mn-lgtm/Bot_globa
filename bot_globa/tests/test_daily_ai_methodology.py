from app.services.daily_horoscope_generation import DAILY_AI_METHOD_VERSION


def test_daily_ai_methodology_has_explicit_version() -> None:
    assert DAILY_AI_METHOD_VERSION == "solar-sign-daily-ai-v1"
