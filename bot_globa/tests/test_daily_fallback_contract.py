from datetime import date

from app.services.daily_horoscope_generation import (
    DAILY_AI_FALLBACK_METHOD_VERSION,
    DailyHoroscopeGenerationService,
)


class _UnusedLLM:
    async def generate_structured(self, request):  # pragma: no cover
        raise AssertionError(request)


def test_daily_fallback_is_a_complete_shared_snapshot() -> None:
    snapshot = DailyHoroscopeGenerationService(_UnusedLLM()).fallback(date(2026, 10, 12))

    assert snapshot.methodology_version == DAILY_AI_FALLBACK_METHOD_VERSION
    assert len(snapshot.signs) == 12
