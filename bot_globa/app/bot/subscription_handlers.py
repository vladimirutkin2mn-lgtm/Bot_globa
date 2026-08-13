"""Telegram subscription checkout and lifecycle management."""

from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.scene_media import Scene, answer_scene
from app.config import Settings
from app.db.models import User
from app.domain.products import ProductCatalog
from app.services.credits_service import CreditsService
from app.services.onboarding import OnboardingService
from app.services.subscription_checkout_service import (
    SubscriptionCheckoutRejectedError,
    SubscriptionCheckoutService,
)
from app.services.subscription_management_service import (
    SubscriptionManagementOutcome,
    SubscriptionManagementService,
    SubscriptionView,
)

router = Router(name="subscriptions")


def subscription_market_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.telegram_stars_enabled:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="Telegram Stars · ⭐",
                        callback_data="credits:stars:subscription_monthly",
                    )
                ]
            ]
        )
    if settings.yookassa_enabled and settings.yookassa_recurring_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Россия · RUB",
                    callback_data="credits:offer:subscription_monthly:RU:RUB",
                )
            ]
        )
    if settings.stripe_enabled:
        for currency in ("EUR", "USD"):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"International · {currency}",
                        callback_data=(
                            f"credits:offer:subscription_monthly:INTERNATIONAL:{currency}"
                        ),
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="Вернуться", callback_data="menu:balance")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_checkout_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть защищённую оплату", url=url)],
            [InlineKeyboardButton(text="Обновить статус", callback_data="subscription:refresh")],
        ]
    )


def subscription_management_keyboard(value: SubscriptionView) -> InlineKeyboardMarkup:
    action = (
        InlineKeyboardButton(
            text="Возобновить автопродление",
            callback_data=f"subscription:resume:{value.id}",
        )
        if value.status == "cancel_at_period_end"
        else InlineKeyboardButton(
            text="Отключить автопродление",
            callback_data=f"subscription:cancel:{value.id}",
        )
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [action],
            [InlineKeyboardButton(text="Обновить статус", callback_data="subscription:refresh")],
            [InlineKeyboardButton(text="Вернуться в меню", callback_data="report:menu")],
        ]
    )


def _status_text(value: SubscriptionView) -> str:
    labels = {
        "incomplete": "ожидает первой оплаты",
        "active": "активна",
        "past_due": "платёж не прошёл",
        "cancel_at_period_end": "автопродление отключено",
        "paused": "приостановлена",
    }
    boundary = (
        value.current_period_end.strftime("%d.%m.%Y")
        if value.current_period_end is not None
        else "не определена"
    )
    suffix = (
        f"Доступ сохранится до {boundary}."
        if value.status == "cancel_at_period_end"
        else f"Следующая граница периода: {boundary}."
    )
    return f"Подписка: {labels.get(value.status, value.status)}.\n{suffix}"


def _subscription_scene(value: SubscriptionView) -> Scene:
    if value.status == "cancel_at_period_end":
        return Scene.SUBSCRIPTION_CANCEL
    if value.status == "past_due":
        return Scene.SUBSCRIPTION_PAST_DUE
    if value.status == "active":
        return Scene.SUBSCRIPTION_ACTIVE
    return Scene.SUBSCRIPTION_CHECKOUT


async def _current_user_subscription(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    subscriptions: SubscriptionManagementService | None,
) -> tuple[User | None, SubscriptionView | None]:
    user = await onboarding.current_user(callback.from_user.id)
    current = (
        None if user is None or subscriptions is None else await subscriptions.current(user.id)
    )
    return user, current


@router.callback_query(F.data.in_({"menu:balance", "credits:refresh", "subscription:refresh"}))
async def balance_and_subscription_screen(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    credits: CreditsService,
    catalog: ProductCatalog,
    subscriptions: SubscriptionManagementService | None,
    billing_settings: Settings,
    analysis_price: int,
) -> None:
    await callback.answer()
    user, current = await _current_user_subscription(callback, onboarding, subscriptions)
    if user is None or not isinstance(callback.message, Message):
        return
    balance = await credits.balance(user.id)
    subscription_note = (
        "\n\n" + _status_text(current)
        if current is not None
        else (
            "\n\nМесячная подписка начисляет кредиты после каждого подтверждённого платежа. "
            "Автопродление можно отключить в любой момент."
            if billing_settings.subscriptions_enabled
            else ""
        )
    )
    await answer_scene(
        callback.message,
        _subscription_scene(current) if current is not None else Scene.BALANCE,
        f"Ваш баланс: {balance} кредитов\n"
        f"Один полный разбор стоит: {analysis_price} кредитов"
        f"{subscription_note}",
        reply_markup=(
            subscription_management_keyboard(current)
            if current is not None
            else _products_keyboard(catalog)
        ),
    )


def _products_keyboard(catalog: ProductCatalog) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{product.title} — {product.credits} кр.",
                callback_data=f"credits:buy:{product.code.value}",
            )
        ]
        for product in catalog.all()
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="Обновить баланс", callback_data="credits:refresh")],
            [InlineKeyboardButton(text="Вернуться в меню", callback_data="report:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "credits:buy:subscription_monthly")
async def choose_subscription_market(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    subscriptions: SubscriptionManagementService | None,
    billing_settings: Settings,
) -> None:
    await callback.answer()
    user, current = await _current_user_subscription(callback, onboarding, subscriptions)
    if user is None or not isinstance(callback.message, Message):
        return
    if current is not None:
        await answer_scene(
            callback.message,
            _subscription_scene(current),
            _status_text(current),
            reply_markup=subscription_management_keyboard(current),
        )
        return
    if not billing_settings.subscriptions_enabled:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Подписка сейчас недоступна.",
        )
        return
    keyboard = subscription_market_keyboard(billing_settings)
    if len(keyboard.inline_keyboard) == 1:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Подписка сейчас недоступна.",
        )
        return
    await answer_scene(
        callback.message,
        Scene.SUBSCRIPTION_CHOICE,
        "Выберите способ оплаты ежемесячной подписки. Провайдер покажет сумму, "
        "период и условия автопродления до подтверждения оплаты.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("credits:offer:subscription_monthly:"))
async def create_subscription_checkout(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    subscription_checkout: SubscriptionCheckoutService | None,
    billing_settings: Settings,
) -> None:
    await callback.answer()
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or subscription_checkout is None or not isinstance(callback.message, Message):
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 5:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Этот вариант подписки недоступен.",
        )
        return
    _, _, product_code, market, currency = parts
    try:
        result = await subscription_checkout.create_checkout(
            user.id, product_code, market, currency
        )
    except SubscriptionCheckoutRejectedError:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Подписка сейчас недоступна. Попробуйте позже.",
        )
        return
    if result.url is None:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Подписка создаётся. Обновите статус через несколько секунд.",
        )
        return
    provider = "YooKassa" if market == "RU" else "Stripe"
    await answer_scene(
        callback.message,
        Scene.SUBSCRIPTION_CHECKOUT,
        f"{provider} покажет сумму, период и условия автопродления до подтверждения оплаты.",
        reply_markup=subscription_checkout_keyboard(result.url),
    )


@router.callback_query(F.data.startswith("subscription:cancel:"))
async def cancel_subscription(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    subscriptions: SubscriptionManagementService | None,
) -> None:
    await _change_subscription(callback, onboarding, subscriptions, resume=False)


@router.callback_query(F.data.startswith("subscription:resume:"))
async def resume_subscription(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    subscriptions: SubscriptionManagementService | None,
) -> None:
    await _change_subscription(callback, onboarding, subscriptions, resume=True)


async def _change_subscription(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    subscriptions: SubscriptionManagementService | None,
    *,
    resume: bool,
) -> None:
    user = await onboarding.current_user(callback.from_user.id)
    try:
        subscription_id = UUID((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    if user is None or subscriptions is None:
        await callback.answer("Подписка недоступна.", show_alert=True)
        return
    outcome = (
        await subscriptions.resume(user.id, subscription_id)
        if resume
        else await subscriptions.cancel(user.id, subscription_id)
    )
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if outcome is SubscriptionManagementOutcome.UPDATED:
        current = await subscriptions.current(user.id)
        text = (
            "Автопродление возобновлено."
            if resume
            else "Автопродление отключено. Уже начисленные кредиты сохраняются."
        )
        await answer_scene(
            callback.message,
            Scene.SUBSCRIPTION_RESUME if resume else Scene.SUBSCRIPTION_CANCEL,
            text,
            reply_markup=(
                subscription_management_keyboard(current) if current is not None else None
            ),
        )
    elif outcome is SubscriptionManagementOutcome.ALREADY_SET:
        await answer_scene(
            callback.message,
            Scene.SUBSCRIPTION_RESUME if resume else Scene.SUBSCRIPTION_CANCEL,
            "Состояние подписки уже актуально.",
        )
    elif outcome is SubscriptionManagementOutcome.UNAVAILABLE:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Управление подпиской временно недоступно.",
        )
    else:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Подписка не найдена.",
        )
