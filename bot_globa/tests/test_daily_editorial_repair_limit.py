import pytest

from app.services.daily_horoscope_generation import DailyHoroscopeGenerationService


class _UnusedLLM:
    async def generate_structured(self, request):  # pragma: no cover
        raise AssertionError(request)


def test_daily_editor_repair_is_bounded_to_one_retry() -> None:
    with pytest.raises(ValueError, match="at most one repair"):
        DailyHoroscopeGenerationService(_UnusedLLM(), max_repair_attempts=2)
