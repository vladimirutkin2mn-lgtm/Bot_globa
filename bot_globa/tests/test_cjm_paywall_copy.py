from app.bot import texts


def test_paywall_is_about_the_current_reading_not_the_product_catalog() -> None:
    assert "{price}" in texts.PAYWALL
    assert "как связаны важные детали ситуации" in texts.PAYWALL
    assert "возможные сценарии" in texts.PAYWALL
    assert "до 3 уточняющих вопросов" in texts.PAYWALL
    assert "24 часов" in texts.PAYWALL
    assert "выбрать пакет" not in texts.PAYWALL
