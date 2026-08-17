"""Regression checks for the launch-critical Telegram journey."""

from uuid import uuid4

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.keyboards import (
    consent_keyboard,
    daily_horoscope_keyboard,
    payment_success_keyboard,
    privacy_keyboard,
    reading_resume_callback,
)
from app.bot.telegram_stars_handlers import _invoice_description, payment_support_text
from app.services.telegram_stars_service import TelegramStarsInvoice


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_consent_details_keep_the_selected_persona() -> None:
    consent = consent_keyboard("love")

    assert _callbacks(consent) == [
        "onboarding:consent:love",
        "privacy:details:love",
        "menu:love",
    ]

    privacy = privacy_keyboard("love")
    assert privacy.inline_keyboard[-1][0].text == "← Назад к согласию"
    assert privacy.inline_keyboard[-1][0].callback_data == "privacy:back:love"


def test_daily_cta_describes_the_screen_it_actually_opens() -> None:
    keyboard = daily_horoscope_keyboard()

    assert keyboard.inline_keyboard[1][0].text == "Выбрать оракула"
    assert keyboard.inline_keyboard[1][0].callback_data == "menu:home"
    assert keyboard.inline_keyboard[-1][0].text == "← Назад в меню"
    assert keyboard.inline_keyboard[-1][0].callback_data == "menu:home"


def test_payment_success_returns_to_the_reading_that_started_checkout() -> None:
    reading_id = uuid4()
    resume = f"love:unlock:{reading_id}"
    paywall = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 полный разбор", callback_data="credits:buy:reading_single"
                )
            ],
            [InlineKeyboardButton(text="После оплаты открыть разбор", callback_data=resume)],
        ]
    )

    assert reading_resume_callback(paywall) == resume

    success = payment_success_keyboard(resume)
    assert success.inline_keyboard[0][0].text == "Открыть полный разбор"
    assert success.inline_keyboard[0][0].callback_data == resume
    assert success.inline_keyboard[-1][0].callback_data == "menu:home"


def test_payment_success_rejects_untrusted_resume_callbacks() -> None:
    keyboard = payment_success_keyboard("privacy:confirm_all")

    assert _callbacks(keyboard) == ["menu:home"]


def test_stars_invoice_and_support_never_expose_the_credit_ledger() -> None:
    invoice = TelegramStarsInvoice(
        order_id=uuid4(),
        payload="globa-stars-v1:test",
        title="Один полный разбор",
        description="После оплаты будет начислено 1 кредитов.",
        price_label="Полный персональный разбор",
        amount=40,
        credits=1,
        subscription_period=None,
    )

    description = _invoice_description(invoice)
    support = payment_support_text()

    assert "кредит" not in description.lower()
    assert "кредит" not in support.lower()
    assert "Доступ" in description


def test_love_oracle_menu_matches_the_current_persona_positioning() -> None:
    assert "Любовный оракул — чувства, притяжение и динамика отношений." in texts.MAIN_MENU
