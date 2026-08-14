"""User-facing contracts taken from the approved CJM v2 frame."""

from datetime import date
from uuid import uuid4

from aiogram.types import InlineKeyboardMarkup
from pydantic import SecretStr

from app.bot import texts
from app.bot.daily_horoscope import render_daily_horoscope
from app.bot.keyboards import (
    consent_keyboard,
    daily_settings_keyboard,
    has_payment_routes,
    payment_market_keyboard,
    products_keyboard,
)
from app.bot.persona_flows import TAROT_FLOW
from app.bot.reading_feedback_handlers import _parse as parse_feedback
from app.bot.scene_media import TELEGRAM_CAPTION_LIMIT
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.daily_horoscope import DailyHoroscopeMode


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": "postgresql+asyncpg://u:p@db/x",
        "telegram_bot_token": SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        "content_encryption_key": SecretStr("cjm-v2-test-key"),
        "subscriptions_enabled": True,
        "billing_enabled": True,
        "telegram_stars_enabled": True,
        "telegram_stars_amount_reading_single": 40,
        "telegram_stars_amount_reading_pack_5": 200,
        "telegram_stars_amount_subscription_monthly": 280,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _buttons(keyboard: InlineKeyboardMarkup) -> list[tuple[str, str | None]]:
    return [
        (button.text, button.callback_data) for row in keyboard.inline_keyboard for button in row
    ]


def test_purchase_screen_has_exact_one_five_and_thirty_reading_choices() -> None:
    settings = _settings()

    assert _buttons(products_keyboard(BillingCatalog(settings), settings))[:3] == [
        ("1 полный разбор — 199 ₽ / 40 ⭐", "credits:buy:reading_single"),
        ("5 полных разборов — 699 ₽ / 200 ⭐", "credits:buy:reading_pack_5"),
        ("30 разборов в месяц — 990 ₽ / 280 ⭐", "credits:buy:subscription_monthly"),
    ]

    reading_id = uuid4()
    resumed = _buttons(
        products_keyboard(
            BillingCatalog(settings),
            settings,
            resume_callback=f"tarot:unlock:{reading_id}",
        )
    )
    assert ("После оплаты открыть разбор", f"tarot:unlock:{reading_id}") in resumed
    assert all(callback is None or len(callback.encode()) <= 64 for _, callback in resumed)


def test_purchase_screen_hides_a_subscription_that_cannot_be_checked_out() -> None:
    settings = _settings(subscriptions_enabled=False, telegram_stars_amount_subscription_monthly=0)

    callbacks = [
        callback for _, callback in _buttons(products_keyboard(BillingCatalog(settings), settings))
    ]

    assert "credits:buy:subscription_monthly" not in callbacks
    assert "credits:buy:reading_single" in callbacks


def test_payment_screen_offers_only_the_providers_that_can_settle() -> None:
    stars_only = _settings(stripe_enabled=False, yookassa_enabled=False)

    keyboard = payment_market_keyboard(
        "reading_single",
        catalog=BillingCatalog(stars_only),
        settings=stars_only,
    )

    assert _buttons(keyboard) == [
        ("Telegram Stars · 40 ⭐", "credits:stars:reading_single"),
        ("Вернуться", "menu:balance"),
    ]
    assert has_payment_routes(keyboard)


def test_a_screen_without_any_usable_provider_is_reported_as_having_no_route() -> None:
    none_enabled = _settings(
        telegram_stars_enabled=False,
        stripe_enabled=False,
        yookassa_enabled=False,
        subscriptions_enabled=False,
        telegram_stars_amount_reading_single=0,
        telegram_stars_amount_reading_pack_5=0,
        telegram_stars_amount_subscription_monthly=0,
    )

    keyboard = payment_market_keyboard(
        "reading_single",
        catalog=BillingCatalog(none_enabled),
        settings=none_enabled,
    )

    assert _buttons(keyboard) == [("Вернуться", "menu:balance")]
    assert not has_payment_routes(keyboard)


def test_consent_can_return_to_the_selected_intention() -> None:
    assert _buttons(consent_keyboard("tarot")) == [
        ("Принять и продолжить", "onboarding:consent:tarot"),
        ("Подробнее", "menu:privacy"),
    ]
    assert "Память выключена" in texts.CONSENT
    assert "{days}" in texts.CONSENT


def test_question_and_paid_result_keep_one_decision_per_screen() -> None:
    reading_id = uuid4()

    assert _buttons(TAROT_FLOW.question_keyboard()) == [
        ("Показать пример", "tarot:example"),
        ("Отмена", "tarot:cancel"),
    ]

    assert parse_feedback(f"rfb:hit:{reading_id}") == ("hit", reading_id)
    assert parse_feedback(f"rfb:miss:{reading_id}") == ("miss", reading_id)
    assert parse_feedback(f"rfb:other:{reading_id}") is None
    assert _buttons(TAROT_FLOW.full_result_keyboard(reading_id)) == [
        ("Задать уточняющий вопрос", f"rfu:ask:{reading_id}"),
        ("Попало", f"rfb:hit:{reading_id}"),
        ("Не откликнулось", f"rfb:miss:{reading_id}"),
        ("Главное меню", "tarot:menu"),
    ]


def test_daily_digest_is_common_bounded_and_has_all_signs() -> None:
    digest = render_daily_horoscope(date(2026, 8, 13))

    assert digest == render_daily_horoscope(date(2026, 8, 13))
    assert len(digest) <= TELEGRAM_CAPTION_LIMIT
    assert digest.count("\n♈") == 1
    assert all(sign in digest for sign in ("Овен", "Телец", "Близнецы", "Рыбы"))
    assert "общий развлекательный прогноз" not in digest


def test_daily_delivery_is_default_on_and_can_be_configured_or_disabled() -> None:
    assert _buttons(daily_settings_keyboard()) == [
        ("Отключить ежедневный гороскоп", "daily:set:disabled"),
        ("Изменить часовой пояс", "daily:timezone"),
        ("Вернуться к гороскопу", "menu:daily"),
    ]


def test_daily_settings_show_which_choice_is_already_saved() -> None:
    disabled = _buttons(daily_settings_keyboard(DailyHoroscopeMode.DISABLED))

    assert ("Включить ежедневный гороскоп", "daily:set:morning") in disabled
    assert ("Изменить часовой пояс", "daily:timezone") in disabled
