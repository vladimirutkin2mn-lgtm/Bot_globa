from app.services.daily_horoscope_generation import DAILY_HISTORY_DAYS, DAILY_PROMPT_HISTORY_DAYS


def test_daily_history_windows_are_bounded() -> None:
    assert DAILY_HISTORY_DAYS == 60
    assert 1 <= DAILY_PROMPT_HISTORY_DAYS < DAILY_HISTORY_DAYS
