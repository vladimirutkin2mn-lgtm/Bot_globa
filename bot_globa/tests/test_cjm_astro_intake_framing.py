from app.bot import horoscope_flow


def test_birth_profile_copy_explains_the_one_time_setup_value() -> None:
    assert "один раз рассчитает натальную карту" in horoscope_flow.CONSENT
    assert "день, неделю и месяц" in horoscope_flow.CONSENT
    assert "без повторного ввода данных рождения" in horoscope_flow.CONSENT
    assert "Создадим карту один раз" in horoscope_flow.BIRTH_DATE_PROMPT
