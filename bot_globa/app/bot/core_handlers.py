"""Domain-neutral Telegram onboarding, account, privacy and credit routes."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import texts
from app.bot.consent import ensure_consent, request_consent
from app.bot.daily_horoscope import (
    MODE_CONFIRMATIONS,
    TIMEZONE_ERROR,
    TIMEZONE_PROMPT,
    render_daily_horoscope,
    render_daily_settings,
    render_timezone_saved,
)
from app.bot.keyboards import (
    back_to_balance_keyboard,
    checkout_creating_keyboard,
    checkout_keyboard,
    checkout_unavailable_keyboard,
    consent_keyboard,
    daily_horoscope_keyboard,
    daily_settings_keyboard,
    daily_timezone_keyboard,
    has_payment_routes,
    main_menu_keyboard,
    more_menu_keyboard,
    onboarding_intro_keyboard,
    payment_market_keyboard,
    privacy_confirmation_keyboard,
    privacy_keyboard,
    products_keyboard,
    reading_resume_callback,
    readings_menu_keyboard,
    receipt_contact_keyboard,
)
from app.bot.scene_media import Scene
from app.bot.screen import send_artifact, show_screen
from app.bot.states import DailyHoroscopeStates, OnboardingStates, PaymentStates
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.daily_horoscope import (
    DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
    DailyHoroscopeMode,
    DailyHoroscopePreferenceView,
    daily_horoscope_enabled,
    parse_moscow_time_difference,
)
from app.services.checkout_service import CheckoutRejectedError, CheckoutService
from app.services.credits_service import CreditsService
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.data_deletion import DataDeletionService
from app.services.onboarding import OnboardingService, OnboardingStep, TelegramIdentity
from app.services.payment_service import CheckoutOutcome, PaymentService
from app.services.receipt_contact import InvalidReceiptContactError, validate_receipt_contact

router = Router(name="oracle_core")
_PAYMENT_RESUME_KEY = "payment_resume_callback"
_CONSENT_DESTINATIONS = frozenset({"tarot", "love", "psy", "astro"})


def _identity(callback: CallbackQuery) -> TelegramIdentity:
    telegram_user = callback.from_user
    return TelegramIdentity(
        telegram_user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        language=telegram_user.language_code,
    )


def _consent_destination(data: str | None, prefix: str) -> str | None:
    value = (data or "").removeprefix(prefix)
    return value if value in _CONSENT_DESTINATIONS else None


def _stored_resume(data: dict[str, object]) -> str | None:
    value = data.get(_PAYMENT_RESUME_KEY)
    return value if isinstance(value, str) else None


async def _clear_payment_state(state: FSMContext, data: dict[str, object]) -> None:
    """Drop receipt data while keeping the concrete reading the purchase should return to."""

    resume = _stored_resume(data)
    await state.clear()
    if resume is not None:
        await state.update_data({_PAYMENT_RESUME_KEY: resume})


async def _show_onboarding_step(
    message: Message,
    state: FSMContext,
    step: OnboardingStep,
    *,
    privacy_retention_days: int,
) -> None:
    if step is OnboardingStep.CONSENT:
        await state.set_state(OnboardingStates.waiting_for_consent)
        await show_screen(
            message,
            Scene.ONBOARDING_CONSENT,
            texts.CONSENT.format(days=privacy_retention_days),
            reply_markup=consent_keyboard(),
            state=state,
        )
        return
    await state.clear()
    await show_screen(
        message, Scene.MAIN_MENU, texts.MAIN_MENU, reply_markup=main_menu_keyboard(), state=state
    )


@router.message(CommandStart())
async def start(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    privacy_retention_days: int,
) -> None:
    """Enter the oracle product without reviving legacy relationship-analysis drafts."""

    if message.from_user is None:
        return
    telegram_user = message.from_user
    _, step = await onboarding.start(
        TelegramIdentity(
            telegram_user_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            language=telegram_user.language_code,
        )
    )
    if step is OnboardingStep.CONSENT:
        # CJM v2 lets a new user choose an intention before just-in-time consent.
        await state.set_state(OnboardingStates.waiting_for_consent)
        await show_screen(
            message,
            Scene.ONBOARDING_START,
            texts.WELCOME,
            reply_markup=onboarding_intro_keyboard(),
            state=state,
        )
        return
    await _show_onboarding_step(
        message,
        state,
        step,
        privacy_retention_days=privacy_retention_days,
    )


@router.callback_query(F.data == "onboarding:intro")
async def continue_onboarding(
    callback: CallbackQuery, state: FSMContext, onboarding: OnboardingService
) -> None:
    if await onboarding.current_user(callback.from_user.id) is None:
        await onboarding.start(_identity(callback))
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            texts.MAIN_MENU,
            reply_markup=main_menu_keyboard(),
            state=state,
        )


@router.callback_query(F.data == "onboarding:consent")
async def accept_consent(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    privacy_retention_days: int,
) -> None:
    if await onboarding.current_user(callback.from_user.id) is None:
        await onboarding.start(_identity(callback))
    step = await onboarding.accept_consent(callback.from_user.id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show_onboarding_step(
            callback.message,
            state,
            step,
            privacy_retention_days=privacy_retention_days,
        )


@router.callback_query(F.data == "menu:more")
async def more_screen(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            texts.MORE_MENU,
            reply_markup=more_menu_keyboard(),
            state=state,
        )


@router.callback_query(F.data == "menu:readings")
async def readings_screen(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.HISTORY,
            texts.READINGS_MENU,
            reply_markup=readings_menu_keyboard(),
            state=state,
        )


async def _leave_timezone_input(state: FSMContext) -> None:
    """Close the time-difference prompt without touching any other live scenario.

    The digest the worker pushes carries these buttons, so they are tapped in the middle
    of whatever the user was doing. A blanket `state.clear()` here would silently discard
    an intake question or a receipt contact the user had already typed.
    """

    if await state.get_state() == DailyHoroscopeStates.waiting_for_timezone_difference.state:
        await state.set_state(None)


@router.callback_query(F.data == "menu:daily")
async def daily_horoscope_screen(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _leave_timezone_input(state)
        timezone = DEFAULT_DAILY_HOROSCOPE_TIMEZONE
        user = await onboarding.current_user(callback.from_user.id)
        if user is not None:
            preference = await daily_horoscopes.current(user.id)
            timezone = preference.timezone
        await send_artifact(
            callback.message,
            Scene.DAILY_HOROSCOPE,
            render_daily_horoscope(datetime.now(ZoneInfo(timezone)).date()),
            reply_markup=daily_horoscope_keyboard(),
            state=state,
        )


@router.callback_query(F.data == "daily:settings")
async def daily_horoscope_settings(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await _leave_timezone_input(state)
    user = await onboarding.current_user(callback.from_user.id)
    preference = (
        await daily_horoscopes.current(user.id)
        if user is not None
        else DailyHoroscopePreferenceView(
            DailyHoroscopeMode.MORNING,
            DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
            None,
        )
    )
    await show_screen(
        callback.message,
        Scene.DAILY_SETTINGS,
        render_daily_settings(preference),
        reply_markup=daily_settings_keyboard(preference.mode),
        state=state,
    )


@router.callback_query(F.data.startswith("daily:set:"))
async def set_daily_horoscope(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await callback.message.answer("Сначала отправьте /start.")
        return
    try:
        requested_mode = DailyHoroscopeMode((callback.data or "").removeprefix("daily:set:"))
        mode = (
            DailyHoroscopeMode.MORNING
            if daily_horoscope_enabled(requested_mode)
            else DailyHoroscopeMode.DISABLED
        )
        preference = await daily_horoscopes.configure(user.id, mode)
    except (LookupError, ValueError):
        await callback.message.answer("Не удалось сохранить настройку. Попробуйте ещё раз.")
        return
    await show_screen(
        callback.message,
        Scene.DAILY_SETTINGS,
        f"{MODE_CONFIRMATIONS[mode]}\n\n{render_daily_settings(preference)}",
        reply_markup=daily_settings_keyboard(preference.mode),
        state=state,
    )


@router.callback_query(F.data == "daily:timezone")
async def request_daily_horoscope_timezone(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if await onboarding.current_user(callback.from_user.id) is None:
        await callback.message.answer("Сначала отправьте /start.")
        return
    await state.set_state(DailyHoroscopeStates.waiting_for_timezone_difference)
    await show_screen(
        callback.message,
        Scene.DAILY_SETTINGS,
        TIMEZONE_PROMPT,
        reply_markup=daily_timezone_keyboard(),
        state=state,
    )


@router.message(DailyHoroscopeStates.waiting_for_timezone_difference)
async def set_daily_horoscope_timezone(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    daily_horoscopes: DailyHoroscopePreferenceService,
) -> None:
    if message.from_user is None:
        return
    user = await onboarding.current_user(message.from_user.id)
    if user is None:
        await _leave_timezone_input(state)
        await message.answer("Сначала отправьте /start.")
        return
    try:
        difference = parse_moscow_time_difference(message.text or "")
        preference = await daily_horoscopes.set_moscow_time_difference(user.id, difference)
    except (LookupError, ValueError):
        await show_screen(
            message,
            Scene.DAILY_SETTINGS,
            TIMEZONE_ERROR,
            reply_markup=daily_timezone_keyboard(),
            state=state,
        )
        return
    await _leave_timezone_input(state)
    await show_screen(
        message,
        Scene.DAILY_SETTINGS,
        f"{render_timezone_saved(preference)}\n\n{render_daily_settings(preference)}",
        reply_markup=daily_settings_keyboard(preference.mode),
        state=state,
    )


@router.callback_query(F.data.in_({"report:menu", "menu:home"}))
async def return_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Keep historical generic menu callbacks harmless during the migration."""

    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            texts.MAIN_MENU,
            reply_markup=main_menu_keyboard(),
            state=state,
        )


@router.callback_query(F.data == "menu:privacy")
@router.callback_query(F.data.startswith("privacy:details:"))
async def privacy_screen(
    callback: CallbackQuery, state: FSMContext, privacy_retention_days: int
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        destination = _consent_destination(callback.data, "privacy:details:")
        await show_screen(
            callback.message,
            Scene.PRIVACY,
            texts.PRIVACY_INFO.format(days=privacy_retention_days),
            reply_markup=privacy_keyboard(destination),
            state=state,
        )


@router.callback_query(F.data.startswith("privacy:back:"))
async def privacy_back_to_consent(
    callback: CallbackQuery,
    state: FSMContext,
    privacy_retention_days: int,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    destination = _consent_destination(callback.data, "privacy:back:")
    if destination is None:
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            texts.MAIN_MENU,
            reply_markup=main_menu_keyboard(),
            state=state,
        )
        return
    await request_consent(
        callback.message,
        state,
        privacy_retention_days,
        destination=destination,
    )


@router.callback_query(F.data == "privacy:delete_all")
async def delete_all_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.DELETE_ACCOUNT,
            texts.DELETE_ALL_PROMPT,
            reply_markup=privacy_confirmation_keyboard(),
            state=state,
        )


@router.callback_query(F.data.in_({"privacy:cancel", "privacy:menu"}))
async def delete_all_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        cancelled = callback.data == "privacy:cancel"
        await show_screen(
            callback.message,
            Scene.DELETE_CANCELLED if cancelled else Scene.MAIN_MENU,
            texts.DELETE_ALL_CANCELLED if cancelled else texts.MAIN_MENU,
            reply_markup=main_menu_keyboard(),
            state=state,
        )


@router.callback_query(F.data == "privacy:confirm_all")
async def delete_all_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    data_deletion: DataDeletionService,
) -> None:
    user = await onboarding.current_user(callback.from_user.id)
    if user is not None:
        await data_deletion.delete_account(user.id)
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await send_artifact(
            callback.message, Scene.ACCOUNT_DELETED, texts.DELETE_ALL_DONE, state=state
        )


@router.callback_query(F.data.in_({"menu:balance", "credits:refresh"}))
async def balance_screen(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    credits: CreditsService,
    billing_catalog: BillingCatalog,
    billing_settings: Settings,
    privacy_retention_days: int,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not await ensure_consent(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        privacy_retention_days,
        identity=_identity(callback),
    ):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        return
    balance = await credits.balance(user.id)
    resume = _stored_resume(await state.get_data())
    await show_screen(
        callback.message,
        Scene.BALANCE,
        f"Доступно полных разборов: "
        f"{balance // billing_settings.reading_full_price_credits}.\n\n"
        "Выберите вариант:",
        reply_markup=products_keyboard(
            billing_catalog,
            billing_settings,
            resume_callback=resume,
        ),
        state=state,
    )


def _callback_parts(callback: CallbackQuery) -> list[str]:
    return (callback.data or "").split(":")


@router.callback_query(F.data.startswith("credits:buy:"))
async def buy_credits(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    payments: PaymentService | None,
    billing_catalog: BillingCatalog,
    billing_settings: Settings,
    privacy_retention_days: int,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not await ensure_consent(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        privacy_retention_days,
        identity=_identity(callback),
    ):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        return
    state_data = await state.get_data()
    if await state.get_state() == PaymentStates.waiting_for_receipt_contact.state:
        await _clear_payment_state(state, state_data)
    resume = reading_resume_callback(callback.message.reply_markup)
    if resume is not None:
        await state.update_data({_PAYMENT_RESUME_KEY: resume})
    product_code = _callback_parts(callback)[-1]
    if payments is None or billing_settings.billing_enabled:
        market = payment_market_keyboard(
            product_code,
            catalog=billing_catalog,
            settings=billing_settings,
        )
        if not has_payment_routes(market):
            await show_screen(
                callback.message,
                Scene.CHECKOUT_UNAVAILABLE,
                texts.PURCHASES_PAUSED,
                reply_markup=market,
                state=state,
            )
            return
        await show_screen(
            callback.message,
            Scene.PAYMENT_MARKET,
            "Выберите способ оплаты.",
            reply_markup=market,
            state=state,
        )
        return
    outcome = await payments.create_checkout(user.id, product_code)
    if outcome.outcome is CheckoutOutcome.CREATING:
        await show_screen(
            callback.message,
            Scene.CHECKOUT,
            texts.CHECKOUT_CREATING,
            reply_markup=checkout_creating_keyboard(product_code),
            state=state,
        )
        return
    if (
        outcome.outcome not in {CheckoutOutcome.CREATED, CheckoutOutcome.EXISTING}
        or outcome.checkout is None
    ):
        await show_screen(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            texts.CHECKOUT_UNAVAILABLE,
            reply_markup=payment_market_keyboard(
                product_code,
                catalog=billing_catalog,
                settings=billing_settings,
            ),
            state=state,
        )
        return
    await show_screen(
        callback.message,
        Scene.CHECKOUT,
        "Тестовая оплата — реальные деньги не списываются.",
        reply_markup=checkout_keyboard(outcome.checkout.url, product_code),
        state=state,
    )


@router.callback_query(F.data.startswith("credits:offer:"))
async def create_production_checkout(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    checkout: CheckoutService,
    billing_settings: Settings,
    privacy_retention_days: int,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not await ensure_consent(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        privacy_retention_days,
        identity=_identity(callback),
    ):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        return
    parts = _callback_parts(callback)
    if len(parts) != 5:
        await show_screen(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            texts.CHECKOUT_STALE_BUTTON,
            reply_markup=back_to_balance_keyboard(),
            state=state,
        )
        return
    _, _, product_code, market, currency = parts
    if billing_settings.yookassa_receipts_required and market == "RU" and currency == "RUB":
        await state.set_state(PaymentStates.waiting_for_receipt_contact)
        await state.update_data(product_code=product_code, market=market, currency=currency)
        await show_screen(
            callback.message,
            Scene.RECEIPT_CONTACT,
            texts.RECEIPT_CONTACT,
            reply_markup=receipt_contact_keyboard(product_code),
            state=state,
        )
        return
    try:
        result = await checkout.create_one_time_checkout(user.id, product_code, market, currency)
    except CheckoutRejectedError:
        await show_screen(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            texts.CHECKOUT_UNAVAILABLE,
            reply_markup=checkout_unavailable_keyboard(product_code, market, currency),
            state=state,
        )
        return
    if not result.url:
        await show_screen(
            callback.message,
            Scene.CHECKOUT,
            texts.CHECKOUT_CREATING,
            reply_markup=checkout_creating_keyboard(product_code),
            state=state,
        )
        return
    await show_screen(
        callback.message,
        Scene.CHECKOUT,
        "Откройте защищённую страницу платёжного провайдера.",
        reply_markup=checkout_keyboard(result.url, product_code),
        state=state,
    )


@router.message(PaymentStates.waiting_for_receipt_contact)
async def receive_receipt_contact(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    checkout: CheckoutService,
    privacy_retention_days: int,
    billing_settings: Settings | None = None,
) -> None:
    data = await state.get_data()
    if message.from_user is not None and not await onboarding.analysis_allowed(
        message.from_user.id
    ):
        # A durable FSM can outlive the screen that opened it; a receipt contact is
        # personal data and must not be accepted on an unaccepted-terms account.
        await request_consent(message, state, privacy_retention_days)
        return
    if message.from_user is None or not message.text:
        await _clear_payment_state(state, data)
        await show_screen(
            message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Контакт для чека не получен. Оплата отменена.",
            state=state,
        )
        return
    try:
        contact = validate_receipt_contact(message.text)
        product_code = str(data["product_code"])
        market = str(data["market"])
        currency = str(data["currency"])
        user = await onboarding.current_user(message.from_user.id)
        if user is None:
            raise CheckoutRejectedError("user not found")
        result = await checkout.create_one_time_checkout(
            user.id,
            product_code,
            market,
            currency,
            receipt_contact=contact.value,
        )
    except InvalidReceiptContactError:
        await show_screen(
            message,
            Scene.RECEIPT_CONTACT,
            "Некорректный email или телефон. Проверьте формат и отправьте ещё раз.",
            reply_markup=receipt_contact_keyboard(
                str(data.get("product_code", "reading_single"))
            ),
            state=state,
        )
        return
    except (CheckoutRejectedError, KeyError):
        await _clear_payment_state(state, data)
        await show_screen(
            message,
            Scene.CHECKOUT_UNAVAILABLE,
            texts.CHECKOUT_UNAVAILABLE,
            reply_markup=(
                checkout_unavailable_keyboard(
                    str(data.get("product_code", "reading_single")),
                    str(data.get("market", "RU")),
                    str(data.get("currency", "RUB")),
                )
            ),
            state=state,
        )
        return
    await _clear_payment_state(state, data)
    if result.url:
        await show_screen(
            message,
            Scene.CHECKOUT,
            "Откройте защищённую страницу платёжного провайдера.",
            reply_markup=checkout_keyboard(result.url, product_code),
            state=state,
        )
    else:
        await show_screen(
            message,
            Scene.CHECKOUT,
            texts.CHECKOUT_CREATING,
            reply_markup=checkout_creating_keyboard(product_code),
            state=state,
        )


@router.callback_query(F.data == "credits:receipt:cancel")
async def cancel_receipt_contact(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await show_screen(
            callback.message,
            Scene.MAIN_MENU,
            "Оплата отменена.",
            reply_markup=main_menu_keyboard(),
            state=state,
        )
