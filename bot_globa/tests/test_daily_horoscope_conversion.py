from datetime import date

from app.bot.daily_conversion_handlers import PERSONAL_DAILY_PROMPT, router
from app.bot.daily_horoscope import render_daily_horoscope
from app.bot.horoscope_flow import HOROSCOPE_FLOW, HOROSCOPE_TOPIC_LABELS
from app.bot.keyboards import daily_horoscope_keyboard
from app.bot.scene_media import TELEGRAM_CAPTION_LIMIT


def test_daily_digest_leads_with_a_concrete_personal_forecast_cta() -> None:
    keyboard = daily_horoscope_keyboard()
    primary = keyboard.inline_keyboard[0][0]

    assert primary.text == "✨ Что сегодня важно именно для меня?"
    assert primary.callback_data == "daily:personal"


def test_direct_daily_conversion_handler_is_registered_as_its_own_router() -> None:
    assert router.name == "daily_conversion"
    assert "Сегодня для вас" in PERSONAL_DAILY_PROMPT
    assert "отношения, работа, деньги" in PERSONAL_DAILY_PROMPT


def test_astrologer_makes_today_forecast_the_first_follow_up_choice() -> None:
    assert next(iter(HOROSCOPE_TOPIC_LABELS)) == "day_forecast"
    assert HOROSCOPE_TOPIC_LABELS["day_forecast"] == "☀️ Прогноз на сегодня"
    assert "Прогноз на сегодня" in HOROSCOPE_FLOW.texts.welcome


def test_daily_footer_explains_the_incremental_personal_value_without_bloating_caption() -> None:
    rendered = render_daily_horoscope(date(2026, 8, 16))

    assert "✨ Персональный прогноз: натальная карта + транзиты сегодня." in rendered
    assert "Это общий прогноз по знаку" not in rendered
    assert len(rendered) <= TELEGRAM_CAPTION_LIMIT
