from app.services.daily_horoscope_generation import DAILY_PROMPT_HISTORY_DAYS


def test_daily_prompt_history_is_small_enough_for_one_shared_call() -> None:
    assert DAILY_PROMPT_HISTORY_DAYS == 8
