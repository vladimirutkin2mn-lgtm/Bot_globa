from app.services.daily_horoscope_generation import DAILY_AI_CURRENT_METHODS


def test_daily_ai_method_versions_include_generated_and_fallback_snapshots() -> None:
    assert DAILY_AI_CURRENT_METHODS == {
        "solar-sign-daily-ai-v1",
        "solar-sign-daily-ai-v1-fallback",
    }
