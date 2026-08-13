"""Inline keyboard factories."""

from collections.abc import Sequence
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.pricing import product_price_label
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.daily_horoscope import DailyHoroscopeMode
from app.domain.products import READING_PURCHASE_CODES, ProductCode, format_user_price
from app.providers.payments.base import BillingMarket


def onboarding_intro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать тему", callback_data="onboarding:intro")]
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
            [InlineKeyboardButton(text="💞 Отношения", callback_data="menu:love")],
            [
                InlineKeyboardButton(
                    text="🔮 Выбор и ближайшие сценарии",
                    callback_data="menu:tarot",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌙 Повторяющаяся ситуация",
                    callback_data="menu:psy",
                )
            ],
            [InlineKeyboardButton(text="🪐 Натальная карта", callback_data="menu:astro")],
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
            [InlineKeyboardButton(text="🔮 Расклады", callback_data="tarot:history")],
            [InlineKeyboardButton(text="💞 Отношения", callback_data="love:history")],
            [InlineKeyboardButton(text="🌙 Сценарии", callback_data="psy:history")],
            [InlineKeyboardButton(text="🪐 Астрология", callback_data="astro:history")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:home")],
        ]
    )


def daily_horoscope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мой персональный прогноз", callback_data="menu:astro")],
            [InlineKeyboardButton(text="Задать вопрос Globa", callback_data="menu:home")],
            [InlineKeyboardButton(text="Получать каждый день", callback_data="daily:settings")],
        ]
    )


def daily_settings_keyboard(current: DailyHoroscopeMode | None = None) -> InlineKeyboardMarkup:
    """Offer the four delivery choices and mark the one already saved."""

    options = (
        ("Да, утром", DailyHoroscopeMode.MORNING),
        ("Да, вечером", DailyHoroscopeMode.EVENING),
        ("Только по запросу", DailyHoroscopeMode.ON_REQUEST),
        ("Не присылать", DailyHoroscopeMode.DISABLED),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"✓ {label}" if mode is current else label,
                callback_data=f"daily:set:{mode.value}",
            )
        ]
        for label, mode in options
    ]
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def exit_rows(analysis_id: UUID, *, resend: bool = False) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    if resend:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отправить заново", callback_data=f"intake:reset:{analysis_id}"
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="Отменить", callback_data=f"intake:cancel:{analysis_id}")],
            [
                InlineKeyboardButton(
                    text="Вернуться в меню", callback_data=f"intake:menu:{analysis_id}"
                )
            ],
        ]
    )
    return rows


def cancel_keyboard(analysis_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=exit_rows(analysis_id))


def participant_keyboard(analysis_id: UUID, participants: dict[str, str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"intake:participant:{analysis_id}:{label}")]
        for label, name in participants.items()
    ]
    rows.extend(exit_rows(analysis_id, resend=True))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def goal_keyboard(analysis_id: UUID) -> InlineKeyboardMarkup:
    options = [
        "Есть ли у человека интерес?",
        "Общение стало холоднее?",
        "Стоит ли написать сейчас?",
        "Как лучше ответить?",
        "Что изменилось?",
    ]
    rows = [
        [InlineKeyboardButton(text=value, callback_data=f"intake:goal:{analysis_id}:{index}")]
        for index, value in enumerate(options)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="Свой вопрос", callback_data=f"intake:goal:{analysis_id}:custom"
            )
        ]
    )
    rows.extend(exit_rows(analysis_id, resend=True))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stage_keyboard(analysis_id: UUID) -> InlineKeyboardMarkup:
    options = [
        ("Только познакомились", "new_connection"),
        ("Ходим на свидания", "dating"),
        ("В отношениях", "relationship"),
        ("После расставания", "post_breakup"),
        ("Сложно определить", "unclear"),
        ("Пропустить", "not_provided"),
    ]
    rows = [
        [InlineKeyboardButton(text=text, callback_data=f"intake:stage:{analysis_id}:{code}")]
        for text, code in options
    ]
    rows.extend(exit_rows(analysis_id, resend=True))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def report_actions_keyboard(analysis_id: object) -> InlineKeyboardMarkup:
    value = str(analysis_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Варианты ответа", callback_data=f"report:replies:{value}")],
            [
                InlineKeyboardButton(
                    text="Задать уточняющий вопрос", callback_data=f"report:followup:{value}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Разобрать новый фрагмент", callback_data=f"report:new_fragment:{value}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Удалить разбор", callback_data=f"report:delete_prompt:{value}"
                )
            ],
            [InlineKeyboardButton(text="Вернуться в меню", callback_data="report:menu")],
        ]
    )


def feedback_keyboard(analysis_id: object) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(score), callback_data=f"feedback:{analysis_id}:{score}"
                )
                for score in range(1, 6)
            ]
        ]
    )


def deletion_keyboard(analysis_id: object) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить", callback_data=f"report:delete_confirm:{analysis_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"report:delete_cancel:{analysis_id}"
                )
            ],
        ]
    )


def corrupted_report_keyboard(analysis_id: object) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить разбор",
                    callback_data=f"report:delete_prompt:{analysis_id}",
                )
            ],
            [InlineKeyboardButton(text="Главное меню", callback_data="report:menu")],
        ]
    )


def history_keyboard(
    items: Sequence[tuple[object, str]], page: int, has_next: bool
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"history:open:{item_id}")]
        for item_id, label in items
    ]
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="← Назад", callback_data=f"history:page:{page - 1}")
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(text="Вперёд →", callback_data=f"history:page:{page + 1}")
        )
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="report:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def billing_keyboard(
    analysis_id: UUID, price: int, preview_available: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if preview_available:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Посмотреть бесплатное превью",
                    callback_data=f"billing:preview:{analysis_id}",
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=f"Получить полный отчёт за {price} кредитов",
                    callback_data=f"billing:full:{analysis_id}",
                )
            ],
            [InlineKeyboardButton(text="Купить кредиты", callback_data="menu:balance")],
            [InlineKeyboardButton(text="Вернуться в меню", callback_data="report:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def paywall_keyboard(analysis_id: UUID, preview_available: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Купить один разбор", callback_data="credits:buy:analysis_single"
            )
        ],
        [
            InlineKeyboardButton(
                text="Купить пакет из 5 разборов", callback_data="credits:buy:analysis_pack_5"
            )
        ],
        [
            InlineKeyboardButton(
                text="Купить месячное начисление", callback_data="credits:buy:subscription_monthly"
            )
        ],
        [
            InlineKeyboardButton(
                text="Обновить баланс", callback_data=f"billing:refresh:{analysis_id}"
            )
        ],
    ]
    if preview_available:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Вернуться к превью", callback_data=f"history:open:{analysis_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Вернуться в меню", callback_data="report:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def preview_actions_keyboard(analysis_id: UUID, price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Открыть полный отчёт за {price} кредитов",
                    callback_data=f"billing:unlock:{analysis_id}",
                )
            ],
            [InlineKeyboardButton(text="Купить кредиты", callback_data="menu:balance")],
            [
                InlineKeyboardButton(
                    text="Удалить разбор", callback_data=f"report:delete_prompt:{analysis_id}"
                )
            ],
            [InlineKeyboardButton(text="Вернуться в меню", callback_data="report:menu")],
        ]
    )
