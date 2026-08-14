"""Inline keyboard factories."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.pricing import product_price_label
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.daily_horoscope import DailyHoroscopeMode, daily_horoscope_enabled
from app.domain.products import READING_PURCHASE_CODES, ProductCode, format_user_price
from app.providers.payments.base import BillingMarket


def onboarding_intro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать персонажа", callback_data="onboarding:intro")]
        ]
    )


def consent_keyboard(destination: str | None = None) -> InlineKeyboardMarkup:
    callback = "onboarding:consent"
    if destination is not None:
        callback = f"{callback}:{destination}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Принять и продолжить", callback_data=callback)],
            [InlineKeyboardButton(text="Подробнее", callback_data="menu:privacy")],
        ]
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💞 Любовный оракул", callback_data="menu:love")],
            [InlineKeyboardButton(text="🔮 Таролог", callback_data="menu:tarot")],
            [InlineKeyboardButton(text="🌙 Мистический психолог", callback_data="menu:psy")],
            [InlineKeyboardButton(text="🪐 Астролог", callback_data="menu:astro")],
            [
                InlineKeyboardButton(text="☀️ Гороскоп на сегодня", callback_data="menu:daily"),
                InlineKeyboardButton(text="📚 Мои разборы", callback_data="menu:readings"),
            ],
            [InlineKeyboardButton(text="⋯ Ещё", callback_data="menu:more")],
        ]
    )


def more_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧠 Память", callback_data="menu:memory")],
            [InlineKeyboardButton(text=texts.BALANCE, callback_data="menu:balance")],
            [InlineKeyboardButton(text=texts.PRIVACY, callback_data="menu:privacy")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:home")],
        ]
    )


def readings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔮 Таролог", callback_data="tarot:history")],
            [InlineKeyboardButton(text="💞 Любовный оракул", callback_data="love:history")],
            [InlineKeyboardButton(text="🌙 Мистический психолог", callback_data="psy:history")],
            [InlineKeyboardButton(text="🪐 Астролог", callback_data="astro:history")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:home")],
        ]
    )


def daily_horoscope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мой персональный прогноз", callback_data="menu:astro")],
            [
                InlineKeyboardButton(
                    text=f"Задать вопрос {texts.BRAND_NAME}",
                    callback_data="menu:home",
                )
            ],
            [InlineKeyboardButton(text="Настройки", callback_data="daily:settings")],
        ]
    )


def daily_settings_keyboard(current: DailyHoroscopeMode | None = None) -> InlineKeyboardMarkup:
    """Offer one delivery switch plus the user's local-time setting."""

    enabled = daily_horoscope_enabled(current or DailyHoroscopeMode.MORNING)
    toggle_mode = DailyHoroscopeMode.DISABLED if enabled else DailyHoroscopeMode.MORNING
    toggle_label = "Отключить ежедневный гороскоп" if enabled else "Включить ежедневный гороскоп"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=toggle_label,
                    callback_data=f"daily:set:{toggle_mode.value}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить часовой пояс",
                    callback_data="daily:timezone",
                )
            ],
            [InlineKeyboardButton(text="Вернуться к гороскопу", callback_data="menu:daily")],
        ]
    )


def daily_timezone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад в настройки", callback_data="daily:settings")]
        ]
    )


def privacy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить все мои данные", callback_data="privacy:delete_all"
                )
            ],
            [InlineKeyboardButton(text="Вернуться в меню", callback_data="privacy:menu")],
        ]
    )


def privacy_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить безвозвратно", callback_data="privacy:confirm_all"
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="privacy:cancel")],
        ]
    )


def products_keyboard(
    catalog: BillingCatalog,
    settings: Settings,
    *,
    resume_callback: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code in READING_PURCHASE_CODES:
        # A subscription that cannot be checked out must not be advertised: the recurring
        # route would answer the tap with "unavailable" and end the purchase there.
        if code is ProductCode.SUBSCRIPTION_MONTHLY and not settings.subscriptions_enabled:
            continue
        offer = catalog.resolve_product_offer(code, BillingMarket.RU, "RUB")
        reading_count = max(offer.credits // settings.reading_full_price_credits, 1)
        if code is ProductCode.READING_SINGLE:
            choice = "1 полный разбор"
        elif code is ProductCode.READING_PACK_5:
            choice = f"{reading_count} полных разборов"
        else:
            choice = f"{reading_count} разборов в месяц"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{choice} — {product_price_label(catalog, code, settings)}",
                    callback_data=f"credits:buy:{code.value}",
                )
            ]
        )
    if resume_callback is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="После оплаты открыть разбор",
                    callback_data=resume_callback,
                )
            ]
        )
    else:
        rows.append([InlineKeyboardButton(text="Обновить доступ", callback_data="credits:refresh")])
    rows.append([InlineKeyboardButton(text="Вернуться в меню", callback_data="report:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def checkout_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть оплату", url=url)],
            [InlineKeyboardButton(text="Обновить доступ", callback_data="credits:refresh")],
        ]
    )


def payment_market_keyboard(
    product_code: str,
    *,
    catalog: BillingCatalog,
    settings: Settings,
    recurring: bool = False,
) -> InlineKeyboardMarkup:
    """Offer only the routes that can actually complete this purchase.

    A button for a disabled provider costs the buyer a tap and answers with an error, so
    each route is gated on the provider that would have to settle it.
    """

    rows: list[list[InlineKeyboardButton]] = []
    if not settings.permits_new_checkout():
        # Disabled billing and the kill switch reject every route, so any button here would
        # cost the buyer a tap and answer with an error.
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Вернуться", callback_data="menu:balance")]]
        )
    if settings.telegram_stars_enabled:
        stars = catalog.resolve_product_offer(product_code, BillingMarket.TELEGRAM, "XTR")
        if stars.amount_minor > 0:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Telegram Stars · {stars.amount_minor} ⭐",
                        callback_data=f"credits:stars:{product_code}",
                    )
                ]
            )
    if settings.yookassa_enabled and (not recurring or settings.yookassa_recurring_enabled):
        ru = catalog.resolve_product_offer(product_code, BillingMarket.RU, "RUB")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Россия · {format_user_price(ru.amount_minor, ru.currency)}",
                    callback_data=f"credits:offer:{product_code}:RU:RUB",
                )
            ]
        )
    if settings.stripe_enabled:
        for currency in ("EUR", "USD"):
            offer = catalog.resolve_product_offer(
                product_code, BillingMarket.INTERNATIONAL, currency
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=(
                            "International · "
                            f"{format_user_price(offer.amount_minor, offer.currency)}"
                        ),
                        callback_data=f"credits:offer:{product_code}:INTERNATIONAL:{currency}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="Вернуться", callback_data="menu:balance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def has_payment_routes(keyboard: InlineKeyboardMarkup) -> bool:
    """Report whether a market keyboard opens a checkout rather than only going back."""

    return any(
        button.callback_data is not None
        and button.callback_data.startswith(("credits:offer:", "credits:stars:"))
        for row in keyboard.inline_keyboard
        for button in row
    )


def receipt_contact_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отменить", callback_data="credits:receipt:cancel")]
        ]
    )


def checkout_creating_keyboard(product_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Обновить статус",
                    callback_data=f"credits:buy:{product_code}",
                )
            ],
            [InlineKeyboardButton(text="Вернуться", callback_data="menu:balance")],
        ]
    )


def checkout_unavailable_keyboard(
    product_code: str,
    market: str,
    currency: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Повторить",
                    callback_data=f"credits:offer:{product_code}:{market}:{currency}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другой способ",
                    callback_data=f"credits:buy:{product_code}",
                )
            ],
            [InlineKeyboardButton(text="Вернуться", callback_data="menu:balance")],
        ]
    )


def back_to_balance_keyboard() -> InlineKeyboardMarkup:
    """A dead end needs one way forward: back to the current prices and routes."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.BALANCE, callback_data="menu:balance")],
        ]
    )
