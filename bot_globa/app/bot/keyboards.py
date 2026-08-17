"""Inline keyboard factories."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.pricing import product_choice_label
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.daily_horoscope import DailyHoroscopeMode, daily_horoscope_enabled
from app.domain.products import READING_PURCHASE_CODES, ProductCode, format_user_price
from app.providers.payments.base import BillingMarket

_READING_RESUME_PREFIXES = (
    "tarot:unlock:",
    "love:unlock:",
    "psy:unlock:",
    "astro:unlock:",
)


def onboarding_intro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать персонажа", callback_data="onboarding:intro")]
        ]
    )


def consent_keyboard(destination: str | None = None) -> InlineKeyboardMarkup:
    callback = "onboarding:consent"
    privacy_callback = "menu:privacy"
    if destination is not None:
        callback = f"{callback}:{destination}"
        privacy_callback = f"privacy:details:{destination}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Принять и продолжить", callback_data=callback)],
            [InlineKeyboardButton(text="Подробнее", callback_data=privacy_callback)],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
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
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
        ]
    )


def readings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔮 Таролог", callback_data="tarot:history")],
            [InlineKeyboardButton(text="💞 Любовный оракул", callback_data="love:history")],
            [InlineKeyboardButton(text="🌙 Мистический психолог", callback_data="psy:history")],
            [InlineKeyboardButton(text="🪐 Астролог", callback_data="astro:history")],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
        ]
    )


def daily_horoscope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Персональный прогноз на сегодня",
                    callback_data="daily:personal",
                )
            ],
            [InlineKeyboardButton(text="Настройки", callback_data="daily:settings")],
            [InlineKeyboardButton(text="← Назад в меню", callback_data="menu:home")],
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
            [InlineKeyboardButton(text="← Назад к гороскопу", callback_data="menu:daily")],
        ]
    )


def daily_timezone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Назад к настройкам", callback_data="daily:settings")]
        ]
    )


def privacy_keyboard(destination: str | None = None) -> InlineKeyboardMarkup:
    return_callback = "privacy:menu" if destination is None else f"privacy:back:{destination}"
    return_label = "← Назад в меню" if destination is None else "← Назад к согласию"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить все мои данные", callback_data="privacy:delete_all"
                )
            ],
            [InlineKeyboardButton(text=return_label, callback_data=return_callback)],
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
            [InlineKeyboardButton(text="← Назад", callback_data="privacy:cancel")],
        ]
    )


def products_keyboard(
    catalog: BillingCatalog,
    settings: Settings,
    *,
    resume_callback: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    direct_unlock = resume_callback is not None
    for code in READING_PURCHASE_CODES:
        # A subscription that cannot be checked out must not be advertised: the recurring
        # route would answer the tap with "unavailable" and end the purchase there.
        if code is ProductCode.SUBSCRIPTION_MONTHLY and not settings.subscriptions_enabled:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=product_choice_label(
                        catalog,
                        code,
                        settings,
                        direct_unlock=direct_unlock and code is ProductCode.READING_SINGLE,
                    ),
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
    rows.append([InlineKeyboardButton(text="← Назад в меню", callback_data="report:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reading_resume_callback(keyboard: InlineKeyboardMarkup | None) -> str | None:
    """Recover the concrete reading a paywall was opened for, without exposing it in checkout."""

    if keyboard is None:
        return None
    for row in keyboard.inline_keyboard:
        for button in row:
            callback = button.callback_data
            if callback is not None and callback.startswith(_READING_RESUME_PREFIXES):
                return callback
    return None


def payment_success_keyboard(resume_callback: str | None = None) -> InlineKeyboardMarkup:
    """Return a buyer to the thing they paid to unlock before offering generic navigation."""

    rows: list[list[InlineKeyboardButton]] = []
    if resume_callback is not None and resume_callback.startswith(_READING_RESUME_PREFIXES):
        rows.append(
            [InlineKeyboardButton(text="Открыть полный разбор", callback_data=resume_callback)]
        )
    rows.append([InlineKeyboardButton(text="← В главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_back_button(product_code: str) -> InlineKeyboardButton:
    """Return from a provider-specific step to the methods for the same purchase."""

    return InlineKeyboardButton(
        text="← Назад к способам оплаты",
        callback_data=f"credits:buy:{product_code}",
    )


def checkout_keyboard(url: str, product_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть оплату", url=url)],
            [InlineKeyboardButton(text="Обновить доступ", callback_data="credits:refresh")],
            [payment_methods_back_button(product_code)],
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
            inline_keyboard=[
                [InlineKeyboardButton(text="← Назад к пакетам", callback_data="menu:balance")]
            ]
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
            price = format_user_price(offer.amount_minor, offer.currency)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Stripe · {price}",
                        callback_data=f"credits:offer:{product_code}:INTERNATIONAL:{currency}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="← Назад к пакетам", callback_data="menu:balance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def has_payment_routes(keyboard: InlineKeyboardMarkup) -> bool:
    """Report whether a market keyboard opens a checkout rather than only going back."""

    return any(
        button.callback_data is not None
        and button.callback_data.startswith(("credits:offer:", "credits:stars:"))
        for row in keyboard.inline_keyboard
        for button in row
    )


def receipt_contact_keyboard(product_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [payment_methods_back_button(product_code)],
            [InlineKeyboardButton(text="Отменить покупку", callback_data="credits:receipt:cancel")],
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
            [payment_methods_back_button(product_code)],
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
            [payment_methods_back_button(product_code)],
            [InlineKeyboardButton(text="← Назад к пакетам", callback_data="menu:balance")],
        ]
    )


def back_to_balance_keyboard() -> InlineKeyboardMarkup:
    """A dead end needs one way forward: back to the current prices and routes."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Назад к оплате", callback_data="menu:balance")],
        ]
    )
